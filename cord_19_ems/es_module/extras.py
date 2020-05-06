import os
import re
import csv
from collections import defaultdict
import jsonlines
import json


# create a dict mapping sha's to entities and other metadata for all sources
def all_ner_metadata_cross_reference(metadata_csv, ner_json, out):
    # open json, get ents for each paper by doc_ids
    ner_data = {}
    with jsonlines.open(ner_json) as reader:
        for obj in reader:
            doc_id = obj['doc_id']
            doc_sents = obj['sents']
            doc_ents = defaultdict(list)
            for sent in doc_sents:
                ent_list = sent['entities']
                for ent in ent_list:
                    doc_ents[ent['type']].append(ent['text'])
            ner_data[doc_id] = doc_ents

    # open csv file containing the article ids (sha)
    # the index of each line in the csv files corresponds to the doc_ids in the ner_json file
    article_data = {}
    with open(metadata_csv, 'r') as csvf:
        reader = csv.reader(csvf)
        next(reader)
        for i, line in enumerate(reader):
            sha = line[0]
            source = line[1]
            doi = line[3]
            publish_time = line[8]
            journal = line[10]
            has_full_text = line[13]
            if sha:
                article_data[sha] = {"entities": ner_data[i]}
                article_data[sha]['source'] = source
                article_data[sha]['doi'] = doi
                article_data[sha]['publish_time'] = publish_time
                article_data[sha]['journal'] = journal
                article_data[sha]['has_full_text'] = has_full_text

    with open(out, 'w') as f:
        json.dump(article_data, f)

    return article_data


def extract_year(publish_time):
    m = re.match(r"[12][0-9][0-9][0-9]", publish_time)
    if m:
        yr = m.group(0)
    else:
        return 0
    return yr


def untokenize(ent_list):
    if len(ent_list) > 0:
        ents = " ".join([re.sub(r"\s", "_", ent) for ent in ent_list])
        return ents
    else:
        return ""


def load_dataset_to_dict(data_dir):
    articles = {}
    for dirname, subdirs, files in os.walk(data_dir):
        for file in files:
            if file != '.DS_Store':
                with open(os.path.join(dirname, file), 'r') as f:
                    text_data = json.load(f)
                    articles[text_data['paper_id']] = text_data

    return articles


def filter_entities(entlist):
    filtered_ents = []
    for ent in entlist:
        ent = ent.lower()
        ent = re.sub(r"[^A-Za-z0-9\-]", " ", ent)   # remove non-alphanumeric characters, except hyphens
        ent = re.sub(r"\s{2,}", " ", ent)           # remove duplicate spaces
        if len(ent) > 2:                            # remove any entities shorter than 3 characters
            if not re.match(r"fig", ent):           # remove ent that is 'fig' or 'figure'
                filtered_ents.append(ent)
    return filtered_ents
