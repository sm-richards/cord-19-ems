#!/bin/bash

# set up module
python setup.py develop
pip install -r requirements.txt

# build index
python index.py --index_name="another_covid_index" \
--module_dir_path="cord_19_ems/es_module" \
--data_dir_path="cord_19_ems/data" \
--metadata_path="cord_19_ems/data_extras/all_sources_metadata_2020-03-13.csv" \
--ner_path="cord_19_ems/data_extras/CORD-NER-ner.json" \
--meta_ner_path="cord_19_ems/data_extras/cross_ref_data_all_sources.json"

# run web search
python query.py --index_name="another_covid_index"
