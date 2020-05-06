"""
This module implements query interface for an elasticsearch index of the Kaggle CORD-19-EMS Dataset.
"""

from flask import *
from elasticsearch_dsl import Q
from index import Article
from elasticsearch_dsl.utils import AttrList, AttrDict
from elasticsearch_dsl import Search
import re

app = Flask(__name__)
index_name = "another_covid_index"

# initialize global variables for rendering page
tmp_text = ""
tmp_authors = ""
gresults = {}


@app.route("/")
def search():
    return render_template('page_query.html')


@app.route("/results", defaults={'page': 1}, methods=['GET', 'POST'])
@app.route("/results/<page>", methods=['GET', 'POST'])
def results(page):
    """ Handles rendering results for multple types of queries: Search queries and 'More Like This' queries. """
    global tmp_text
    global tmp_authors
    global tmp_search_type
    global tmp_min
    global tmp_max
    global tmp_lang
    global gresults
    global tmp_doc_id
    global tmp_search_operator

    # instantiate a search object
    s = Search(index=index_name)

    # make sure 'page' id is an int
    if type(page) is not int:
        page = int(page.encode('utf-8'))

    # initialize variables differently depending on whether method is GET or POST --------------------------------------
    if request.method == 'POST':
        search_type = request.form['type']  # 'more_like_this' or 'search'
        tmp_search_type = search_type

        # More Like This Queries
        if search_type !='search':
            tmp_doc_id = request.form['query']

        # Standard Queries
        else:
            text_query = request.form['query']
            authors_query = request.form['authors']
            lang_query = request.form['in_english']
            search_operator = request.form.get('search_operator')  # conjunctive or disjunctive search

            # handle date range
            mindate_query = request.form['mindate']
            mindate_query = int(mindate_query) if len(mindate_query) > 0 else 0
            maxdate_query = request.form['maxdate']
            maxdate_query = int(maxdate_query) if len(maxdate_query) > 0 else 99999

            # update global variable template data
            tmp_text = text_query
            tmp_authors = authors_query
            tmp_min = mindate_query
            tmp_max = maxdate_query
            tmp_lang = lang_query
            tmp_search_operator = search_operator

    else:  # request.method == 'GET':
        search_operator = tmp_search_operator
        search_type = tmp_search_type
        text_query = tmp_text
        authors_query = tmp_authors
        mindate_query = tmp_min if tmp_min > 0 else ""
        maxdate_query = tmp_max if tmp_max < 99999 else ""
        lang_query = tmp_lang

    # Search type is either MORE LIKE THIS or STANDARD SEARCH-----------------------------------------------------------
    if search_type == 'more_like_this_citations':
        print(tmp_doc_id)
        return more_like_this(page, s, tmp_doc_id)
    elif search_type == 'more_like_this_entities':
        return more_like_this_ents(page, s, tmp_doc_id)
    elif search_type == 'match_entity':
        return more_like_this_ents(page, s, tmp_doc_id, single_ent=True)

    # ---------------STANDARD SEARCH--------------- #
    shows = {'text': text_query, 'authors': authors_query, 'maxdate': maxdate_query, 'mindate': mindate_query,
             'lang': lang_query}

    # match language
    if lang_query == True:
        s = s.query('match', in_english=lang_query)

    # match publish time
    s = s.query('range', publish_time={'gte': mindate_query, 'lte': maxdate_query})

    # free text search
    if len(text_query) > 0:
        s = s.query('multi_match', query=text_query, type='cross_fields',
                fields=['title', 'abstract', 'body'], operator=search_operator)

    # authors search
    if len(authors_query) > 0:
        s = filter_for_authors(authors_query, s)
    # if no query is passed in, return all documents
    else:
        s = s.query('match_all')

    # highlight
    s = s.highlight_options(pre_tags='<mark>', post_tags='</mark>')
    s = s.highlight('abstract', fragment_size=999999999, number_of_fragments=1)
    s = s.highlight('title', fragment_size=999999999, number_of_fragments=1)

    # determine the subset of results to display (based on current <page> value)
    start = 0 + (page - 1) * 10
    end = 10 + (page - 1) * 10

    # execute search and return results in specified range.
    response = s[start:end].execute()
    result_num = response.hits.total['value']

    # get data for each hit, to display on results page
    results = populate_results(response)

    # make the result list available globally
    gresults = results

    if result_num > 0:
        return render_template('page_SERP.html', results=results,
                               res_num=result_num, page_num=page, queries=shows)
    else:
        message = []
        if len(text_query) > 0:
            message.append('No documents matching query: ' + text_query)
        if len(authors_query) > 0:
            message.append('Cannot find authors: ' + authors_query)

        return render_template('page_SERP.html', results=message, res_num=result_num,
                               page_num=page, queries=shows)


def more_like_this_ents(page, s, doc_id, single_ent=False):
    global gresults
    article = Article.get(id=doc_id, index=index_name)
    title = article['title']

    # execute a query for articles containing matching entities
    if single_ent:
        ent = request.form['ent']
        s = s.query('multi_match', query=ent, fields=['ents'], operator='and', type='cross_fields')
    else:
        q = Q("more_like_this", fields=["ents"], like=[{"_index": index_name, "_id": doc_id}], min_term_freq=1)
        s = s.query(q)

    # display results by 10
    start = 0 + (page - 1) * 10
    end = 10 + (page - 1) * 10

    # execute search and return results in specified range.
    response = s[start:end].execute()
    result_num = response.hits.total['value']

    # get data for each hit, to display on results page
    results = populate_results(response)

    # dummy placeholder for citation overlap
    for i in results:
        results[i]['overlap'] = ""

    # make the result list available globally
    gresults = results

    # get the total number of matching results
    return render_template('more_like_this.html', results=results, doc_id=doc_id, title=title,
                           res_num=result_num, page_num=page)


def more_like_this(page, s, doc_id):
    global gresults

    # Grab the actual article from the index
    article = Article.get(id=doc_id, index=index_name)
    title = article['title']

    # grab a list of citation titles for this article, for comparison
    citations = set([citation['title'] for citation in article['citations']])

    # execute a query for articles containing matching citations
    q = Q('bool',
          should=[{"match_phrase": {'citations.title': citation} for citation in citations}],
          minimum_should_match=1)
    s = s.query("nested", path="citations", query=q)

    # display results by 10
    start = 0 + (page - 1) * 10
    end = 10 + (page - 1) * 10

    # execute search and return results in specified range.
    response = s[start:end].execute()
    result_num = response.hits.total['value']

    # get data for each hit, to display on results page
    results = populate_results(response)
    if doc_id in results.keys():
        del results[doc_id]

    # calculate percentage citation overlap between each result article and reference article
    # use this to display on the page
    get_citation_overlap_scores(citations, results)

    # make the result list available globally

    # get the total number of matching results
    return render_template('more_like_this.html', results=results, doc_id=doc_id, title=title,
                           res_num=result_num, page_num=page)


def get_citation_overlap_scores(citations, results):
    """ Finds percentage overlap in citations between two documents.
    Used for display on 'more like this' page. """
    for i in results:
        result = results[i]
        hit_citations = set([citation['title'] for citation in result['citations']])
        overlap = len(citations.intersection(hit_citations)) / len(citations)
        result['overlap'] = overlap


def filter_for_authors(authors_query, s):
    """ Filters an existing search object, s, for documents that match the authors query"""
    authors = authors_query.split(";")
    for author in authors:
        author = author.strip(" ")
        names = author.split(" ")
        if len(names) > 1:
            first_name = names[0]
            last_name = names[1]
            q = Q('bool',
                  must=[{"match": {'authors.first': first_name}}, {"match": {'authors.last': last_name}}])
            s = s.filter("nested", path="authors", query=q)
        else:
            q = Q('bool', must=[{"match": {'authors.first': author}}]) \
                | Q('bool', must=[{"match": {'authors.last': author}}])
            s = s.filter("nested", path="authors", query=q)
    return s


def populate_results(response):
    """ Fills out the results metadata for each hit in 'response' """
    results = {}
    for hit in response.hits:
        result = {'score': hit.meta.score,
                  'citations': hit.citations,
                  'body': hit.body}

        # add highlighting
        if 'highlight' in hit.meta:
            result['title'] = hit.meta.highlight.title[0] if 'title' in hit.meta.highlight else hit.title
            result['abstract'] = hit.meta.highlight.abstract[0] if 'abstract' in hit.meta.highlight else hit.abstract
        else:
            result['title'] = hit.title
            result['abstract'] = hit.abstract

        # get entities
        article = Article.get(id=hit.meta.id, index=index_name)
        entlist = list(set(article['ents'].split()))  # remove duplicates
        result['entities_list'] = [{'query': ent, 'display': re.sub(r"_", " ", ent)} for ent in entlist]
        result['id'] = hit.meta.id

        results[hit.meta.id] = result

    return results


# display a particular document given a result number
@app.route("/documents/<res>", methods=['GET'])
def documents(res):
    article = Article.get(id=res, index=index_name)
    article_title = article['title']
    return render_template('page_targetArticle.html', article=article, title=article_title)


if __name__ == "__main__":
    app.run(debug=True)
