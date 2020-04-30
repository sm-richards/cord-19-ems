An elasticsearch information retrieval system for Kaggle's 
[COVID-19 Open Research Dataset Challenge (CORD-19)](https://www.kaggle.com/allen-institute-for-ai/CORD-19-research-challenge)

* Task: What do we know about virus genetics, origin, and evolution?
* Authors: Samantha Richards, Emily Fountain, Molly Moran

### Set Up
Navigate to the Cord-19-EMS outer project directory and run

 `python setup.py develop`
 
which will set up the package structure and install all dependencies in requirements.txt

### Package Structure
Main package name: cord_19_ems
Subdirectories:
* es_module: contains all code for building and querying an elasticsearch index
* notebooks: various additional modules that add features to the search engine

### Build and Query
To build the search index, navigate to the package directory cord_19_ems, 
navigate to the es_module subdirectory, and run:

 `python index.py`
 
 To launch the search engine and begin querying the dataset, run
 
  `python query.py`

### Modules

* Citation_Network : ...



