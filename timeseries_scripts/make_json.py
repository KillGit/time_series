"""
Open Power System Data

Timeseries Datapackage

make:json.py : create JSON meta data for the Data Package

"""

import pandas as pd
import pycountry
import json
import yaml

# General metadata

metadata_head = '''
name: opsd_time_series

title: Time series

description: Load, wind and solar, prices in hourly resolution

long_description: This data package contains different kinds of timeseries
    data relevant for power system modelling, namely electricity consumption 
    (load) for 36 European countries as well as wind and solar power generation
    and capacities and prices for a growing subset of countries. 
    The timeseries become available at different points in time depending on the
    sources. The
    data has been downloaded from the sources, resampled and merged in
    a large CSV file with hourly resolution. Additionally, the data
    available at a higher resolution (Some renewables in-feed, 15
    minutes) is provided in a separate file. All data processing is
    conducted in python and pandas and has been documented in the
    Jupyter notebooks linked below.
documentation: https://github.com/Open-Power-System-Data/datapackage_timeseries/blob/{version}/main.ipynb

version: '{version}'

last_changes: Included data from CEPS and PSE

keywords:
    - Open Power System Data
    - time series
    - power systems
    - in-feed
    - renewables
    - wind
    - solar
    - power consumption
    - power market

geographical-scope: 35 European countries

contributors:
    - web: http://neon-energie.de/en/team/
      name: Jonathan Muehlenpfordt
      email: muehlenpfordt@neon-energie.de

resources:
'''

source_template = '''
    - name: {source}
#      web: {web}
'''

resource_template = '''
    - path: time_series_{res_key}_singleindex.csv
      format: csv
      mediatype: text/csv
      encoding: UTF8
      dialect: 
          csvddfVersion: 1.0
          delimiter: ","
          lineTerminator: "\\n" 
          header: true
      alternative_formats:
          - path: time_series_{res_key}_singleindex.csv
            stacking: Singleindex
            format: csv
          - path: time_series.xlsx
            stacking: Multiindex
            format: xlsx
          - path: time_series_{res_key}_multiindex.csv
            stacking: Multiindex
            format: csv
          - path: time_series_{res_key}_stacked.csv
            stacking: Stacked
            format: csv
      schema:
          primaryKey: {utc}
          missingValue: ""
          fields:
'''

indexfield = '''
            - name: {utc}
              description: Start of timeperiod in Coordinated Universal Time
              type: datetime
              format: fmt:%Y-%m-%dT%H%M%SZ
              opsd-contentfilter: true
            - name: {cet}
              description: Start of timeperiod in Central European (Summer-) Time
              type: datetime
              format: fmt:%Y-%m-%dT%H%M%S%z
            - name: {marker}
              description: marker to indicate which columns are missing data in source data and has been interpolated (e.g. solar_DE-transnetbw_generation;)
              type: string
'''

field_template = '''
            - name: {variable}_{region}_{attribute}
              description: {description}
              type: number (float)
              source:
                  name: {source}
                  web: {web}
              opsd-properties: 
                  Region: {region}
                  Variable: {variable}
                  Attribute: {attribute}
'''

descriptions_template = '''
load: Consumption in {geo} in MW
generation: Actual {tech} generation in {geo} in MW
actual: Actual {tech} generation in {geo} in MW
forecast: Forecasted {tech} generation forecast in {geo} in MW
capacity: Electrical capacity of {tech} in {geo} in MW
profile: Share of {tech} capacity producing in {geo}
epex: Day-ahead spot price for {geo}
elspot: Day-ahead spot price for {geo}
'''

# Columns-specific metadata

# For each dataset/outputfile, the metadata has an entry in the
# "resources" list that describes the file/dataset. The main part of each
# entry is the "schema" dictionary, consisting of a list of "fields",
# meaning the columns in the dataset. The first field is the timestamp
# index of the dataset. For the other fields, we iterate over the columns
# of the MultiIndex index of the datasets to contruct the corresponding
# metadata.


def make_json(data_sets, info_cols, version, headers):
    '''
    Create a datapackage.json file that complies with the Frictionless
    data JSON Table Schema from the information in the column-MultiIndex.
    
    Parameters
    ----------
    data_sets: dict of pandas.DataFrames
        A dict with keys '15min' and '60min' and values the respective
        DataFrames
    info_cols : dict of strings
        Names for non-data columns such as for the index, for additional 
        timestamps or the marker column
    version: str
        Version tag of the Data Package
    headers : list
        List of strings indicating the level names of the pandas.MultiIndex
        for the columns of the dataframe.
    
    Returns
    ----------
    None
    
    '''

    resource_list = ''  # list of files included in the datapackage
    source_list = ''  # list of sources were data comes from
    for res_key, df in data_sets.items():
        # Create the list of of columns in a file, starting with the index field
        field_list = indexfield.format(**info_cols)
        for col in df.columns:
            if col[0] in info_cols.values():
                continue
            h = {k: v for k, v in zip(headers, col)}
            if len(h['region']) > 2:
                geo = h['region'] + ' balancing area'
            elif h['region'] == 'NI':
                geo = 'Northern Ireland'
            elif h['region'] == 'CS':
                geo = 'Serbia and Montenegro'
            else:
                geo = pycountry.countries.get(alpha2=h['region']).name

            descriptions = yaml.load(
                descriptions_template.format(tech=h['variable'], geo=geo)
            )
            h['description'] = descriptions[h['attribute']]
            field_list = field_list + field_template.format(**h)
            source_list = source_list + source_template.format(**h)
        resource_list = resource_list + \
            resource_template.format(res_key=res_key, **info_cols) + field_list

    # Remove duplicates from sources_list. set() returns unique values from a
    # collection, but it cannot compare dicts. Since source_list is a list of of
    # dicts, this requires some juggling with data types
    source_list = [dict(tupleized)
                   for tupleized in set(tuple(entry.items())
                                        for entry in yaml.load(source_list))]

    metadata = yaml.load(metadata_head.format(version=version))
    metadata['sources'] = source_list
    metadata['resources'] = yaml.load(resource_list)
    for resource in metadata['resources']:
        for field in resource['schema']['fields']:
            if 'source' in field.keys() and field['source']['name'] == 'own calculation':
                del field['source']['web']

    # write the metadata to disk
    datapackage_json = json.dumps(metadata, indent=4, separators=(',', ': '))
    with open('datapackage.json', 'w') as f:
        f.write(datapackage_json)
        
    return

