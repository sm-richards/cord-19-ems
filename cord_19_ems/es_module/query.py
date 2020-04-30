"""
This module implements query interface for an elasticsearch index of the Kaggle CORD-19-EMS Dataset.
"""

from flask import *
from elasticsearch_dsl import Q
from index import Article
from elasticsearch_dsl.utils import AttrList
from elasticsearch_dsl import Search

app = Flask(__name__)

# Initialize global variables for rendering page
tmp_text = ""
tmp_authors = ""
gresults = {}

@app.route("/")
def search():
    return render_template('page_query.html')

@app.route("/results", defaults={'page': 1}, methods=['GET', 'POST'])
@app.route("/results/<page>", methods=['GET', 'POST'])
def results(page):
    global tmp_text
    global tmp_authors
    global tmp_type
    global gresults

    if type(page) is not int:
        page = int(page.encode('utf-8'))
    if 'title' in request.form:

        # then this is a more_like_this query.
        doc_id = int(request.form['query'])
        s = Search(index='covid_index')
        article = Article.get(id=doc_id, index='covid_index')
        citations = article['citations']
        q = Q('bool',
              should= [{"match": {'citations.title': citation['title']} for citation in citations}],
                          minimum_should_match=1)
        s = s.query("nested", path="citations", query=q)
        start = 0 + (page - 1) * 10
        end = 10 + (page - 1) * 10

        # execute search and return results in specified range.
        response = s[start:end].execute()

        # insert data into response
        results = {}
        for hit in response.hits:
            print(hit.meta)
            result = {}
            result['score'] = hit.meta.score

            if 'highlight' in hit.meta:
                if 'title' in hit.meta.highlight:
                    result['title'] = hit.meta.highlight.title[0]
                else:
                    result['title'] = hit.title

                if 'abstract' in hit.meta.highlight:
                    result['abstract'] = hit.meta.highlight.abstract[0]
                else:
                    result['abstract'] = hit.abstract
            else:
                result['title'] = hit.title
                result['abstract'] = hit.abstract
            result['body'] = hit.body
            results[hit.meta.id] = result

        # make the result list available globally
        gresults = results

        # get the total number of matching results
        result_num = response.hits.total['value']
        return render_template('more_like_this.html', results=results, title=request.form['title'], res_num=result_num, page_num=page)

    if request.method == 'POST':
        text_query = request.form['query']
        authors_query = request.form['authors']
        search_type = request.form.get('search_type')

        # update global variable template data
        tmp_text = text_query
        tmp_authors = authors_query
        tmp_type = search_type

    else:
        # use the current values stored in global variables.
        search_type = tmp_type
        text_query = tmp_text
        authors_query = tmp_authors
    # store query values to display in search boxes in UI
    shows = {}
    shows['text'] = text_query
    shows['authors'] = authors_query

    # Create a search object to query our index
    s = Search(index='covid_index')

    # Conjunctive search over multiple fields (title, abstract and body) using the text_query passed in

    if len(text_query) > 0:
        print(text_query)
        if search_type == 'Conjunctive':
            operator = 'and'
        else:
            operator = 'or'
        s = s.query('multi_match', query=text_query, type='cross_fields', fields=['title', 'abstract', 'body'], operator=operator)

    # Supports multiple names separated by a list
    if len(authors_query) > 0:
        # users can search for multiple authors separated by semicolons.
        # grab each individual name by splitting on semicolons
        authors = authors_query.split(";")
        for author in authors:
            author = author.strip(" ")
            # grab first and last name, if applicable, for a particular author, by splitting on space
            names = author.split(" ")
            # if more than one name is given...
            if len(names) > 1:
                first_name = names[0]
                last_name = names[1]
                # run a compound query over the first_name and last_name fields of each individual author.
                # requires that both first and last name match
                q = Q('bool',
                      must=[
                          {"match": {'authors.first': first_name}}, {"match": {'authors.last': last_name}}
                      ])
                s = s.filter("nested", path="authors", query=q)
            # if only one name is included for a particular author, return a doc if either first_name or last_name
            # matches the queried name, for any author in the doc
            else:
                q = Q('bool',
                      must=[
                          {"match": {'authors.first': author}}]) | Q('bool',must=[{"match": {'authors.last': author}}])
                s = s.filter("nested", path="authors", query=q)

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

    # insert data into response
    resultList = {}
    for hit in response.hits:
        result = {}
        result['score'] = hit.meta.score

        if 'highlight' in hit.meta:
            if 'title' in hit.meta.highlight:
                result['title'] = hit.meta.highlight.title[0]
            else:
                result['title'] = hit.title

            if 'abstract' in hit.meta.highlight:
                result['abstract'] = hit.meta.highlight.abstract[0]
            else:
                result['abstract'] = hit.abstract
        else:
            result['title'] = hit.title
            result['abstract'] = hit.abstract
        result['body'] = hit.body
        resultList[hit.meta.id] = result

    # make the result list available globally
    gresults = resultList

    # get the total number of matching results
    result_num = response.hits.total['value']

    # if we find the results, extract title and abstract information from doc_data, else do nothing
    if result_num > 0:
        return render_template('page_SERP.html', results=resultList, res_num=result_num, page_num=page, queries=shows)
    else:
        message = []
        if len(text_query) > 0:
            message.append('No documents found matching all fields containing any of the following terms: ' + text_query)
        if len(authors_query) > 0:
            message.append('Cannot find authors: ' + authors_query)

        return render_template('page_SERP.html', results=message, res_num=result_num, page_num=page, queries=shows)


# display a particular document given a result number
@app.route("/documents/<res>", methods=['GET'])
def documents(res):
    global gresults
    article = gresults[res]
    article_title = article['title']
    for term in article:
        if type(article[term]) is AttrList:
            s = "\n"
            for item in article[term]:
                s += item + ",\n "
            article[term] = s
    # fetch the movie from the elasticsearch index using its id
    article = Article.get(id=res, index='covid_index')
    articledict = article.to_dict()
    return render_template('page_targetArticle.html', article=article, title=article_title)

if __name__ == "__main__":
    app.run(debug=True)