"""
Open Power System Data

Timeseries Datapackage

read.py : read time series files

"""
import pytz
import yaml
import os
import sys
import numpy as np
import pandas as pd
import logging
import zipfile
from datetime import datetime, date, time, timedelta

logger = logging.getLogger('log')
logger.setLevel('DEBUG')


def read_pse(filepath, variable_name, url, headers):
    """
    Read a .csv file from PSE into a DataFrame.

    Parameters
    ----------
    filepath : str
        Directory path of file to be read
    variable_name : str
        Name of variable, e.g. ``solar``
    url : str
        URL linking to the source website where this data comes from
    headers : list
        List of strings indicating the level names of the pandas.MultiIndex
        for the columns of the dataframe

    Returns
    ----------
    df: pandas.DataFrame
        The content of one file from PSE

    """
    
    df = pd.read_csv(
        filepath,
        sep=';',
        encoding='cp1250',
        header=0,
        index_col=None,  # 'timestamp',
        names=None,
        parse_dates=None,  # {'timestamp': ['Data', 'Godzina']},
        date_parser=None,
        dayfirst=False,
        decimal=',',
        thousands=None,
        # hours are indicated by their ending time. During fall DST,
        # UTC 23:00-00:00 = CEST 1:00-2:00 is indicated by '02',
        # UTC 00:00-01:00 = CEST 2:00-3:00 is indicated by '02A',
        # UTC 01:00-02:00 = CET  2:00-3:00 is indicated by '03'.
        # regular hours require backshifting by 1 period
        converters={'Godzina': lambda x: '2:00' if x ==
                    '02A' else str(int(x) - 1) + ':00'},
        usecols=None,
    )
    # Create a list of spring-daylight savings time (DST)-transitions
    dst_transitions_spring = [
        d.replace(hour=2)
        for d in pytz.timezone('Europe/Copenhagen')._utc_transition_times
        if d.year >= 2000 and d.month == 3]

    # The hour from 01:00 - 02:00 is indexed by "03:00",
    # requiring backshifting by another period

    df['timestamp'] = pd.to_datetime(
        df['Data'].astype(str) + ' ' +
        df['Godzina'])

    slicer = df['timestamp'].isin(dst_transitions_spring)
    df.loc[slicer, 'Godzina'] = '1:00'

    df['timestamp'] = pd.to_datetime(
        df['Data'].astype(str) + ' ' +
        df['Godzina'])
    df.set_index('timestamp', inplace=True)

    # 'ambigous' refers to how the October dst-transition hour is handled.
    # ‘infer’ will attempt to infer dst-transition hours based on order.
    df.index = df.index.tz_localize('Europe/Berlin', ambiguous='infer')
    df.index = df.index.tz_convert(None)

    # Translate columns
    colmap = {'Sumaryczna generacja źródeł wiatrowych': (
        'wind', 'PL', 'generation', 'PSE', url)}

    # Drop any column not in colmap
    df = df[list(colmap.keys())]

    # Create the MultiIndex.
    tuples = [colmap[col] for col in df.columns]
    df.columns = pd.MultiIndex.from_tuples(tuples, names=headers)

    return df


def read_ceps(filepath, variable_name, url, headers):
    '''Read a file from CEPS into a DataFrame'''
    df = pd.read_excel(
        io=filepath,
        header=2,
        skiprows=None,
        index_col=0,
        parse_cols=[0, 1, 2]
    )

    df.index = pd.to_datetime(df.index.rename('timestamp'))

    df.index = df.index.tz_localize('Europe/Brussels', ambiguous='infer')
    df.index = df.index.tz_convert(None)

    # Translate columns
    colmap = {'WPP [MW]': ('wind-onshore', 'CZ', 'generation', 'CEPS', url),
              'PVPP [MW]': ('solar', 'CZ', 'generation', 'CEPS', url), }

    # Create the MultiIndex.
    tuples = [colmap[col] for col in df.columns]
    df.columns = pd.MultiIndex.from_tuples(tuples, names=headers)

    return df


def read_elia(filepath, variable_name, url, headers):
    '''Read a file from Elia into a DataFrame'''
    df = pd.read_excel(
        io=filepath,
        header=None,
        skiprows=4,
        index_col=0,
        parse_cols=[0, 2, 4, 5]
    )

    df.columns = ['forecast', 'generation', 'capacity']

    df.index = pd.to_datetime(df.index.rename('timestamp'))

    df.index = df.index.tz_localize('Europe/Brussels', ambiguous='infer')
    df.index = df.index.tz_convert(None)

    # Create the MultiIndex
    tuples = [(variable_name, 'BE', attribute, 'Elia', url)
              for attribute in df.columns]
    df.columns = pd.MultiIndex.from_tuples(tuples, names=headers)

    return df


def read_energinet_dk(filepath, url, headers):
    '''Read a file from energinet.dk into a DataFrame'''
    df = pd.read_excel(
        io=filepath,
        header=2,  # the column headers are taken from 3rd row.
        # 2nd row also contains header info like in a multiindex,
        # i.e. wether the colums are price or generation data.
        # However, we will make our own columnnames below.
        # Row 3 is enough to unambigously identify the columns
        skiprows=None,
        index_col=None,
        parse_cols=None,  # None means: parse all columns
        thousands=','
    )

    df.index.rename(['date', 'hour'], inplace=True)
    df.reset_index(inplace=True)
    df['timestamp'] = pd.to_datetime(
        df['date'].astype(str) + ' ' +
        (df['hour'] - 1).astype(str) + ':00')
    df.set_index('timestamp', inplace=True)

    # Create a list of spring-daylight savings time (DST)-transitions
    dst_transitions_spring = [
        d.replace(hour=2)
        for d in pytz.timezone('Europe/Copenhagen')._utc_transition_times
        if d.year >= 2000 and d.month == 3]

    # Drop 3rd hour for (spring) DST-transition from df.
    df = df[~df.index.isin(dst_transitions_spring)]

    dst_arr = np.ones(len(df.index), dtype=bool)
    df.index = df.index.tz_localize('Europe/Copenhagen', ambiguous=dst_arr)
    df.index = df.index.tz_convert(None)

    source = 'Energinet.dk'
    colmap = {
        'DK-West':
            ('price', 'DK-west', 'elspot', source, url),
        'DK-East':
            ('price', 'DK-east', 'elspot', source, url),
        'Norway':
            ('price', 'NO', 'elspot', source, url),
        'Sweden (SE)':
            ('price', 'SE', 'elspot', source, url),
        'Sweden (SE3)':
            ('price', 'SE-3', 'elspot', source, url),
        'Sweden (SE4)':
            ('price', 'SE-4', 'elspot', source, url),
        'DE European Power Exchange':
            ('price', 'DE', 'epex', source, url),
        'DK-West: Wind power production':
            ('wind', 'DK-west', 'generation', source, url),
        'DK-West: Solar cell production (estimated)':
            ('solar', 'DK-west', 'generation', source, url),
        'DK-East: Wind power production':
            ('wind', 'DK-east', 'generation', source, url),
        'DK-East: Solar cell production (estimated)':
            ('solar', 'DK-east', 'generation', source, url),
        'DK: Wind power production (onshore)':
            ('wind-onshore', 'DK', 'generation', source, url),
        'DK: Wind power production (offshore)':
            ('wind-offshore', 'DK', 'generation', source, url)
    }

    # Drop any column not in colmap
    df = df[list(colmap.keys())]

    # Create the MultiIndex.
    tuples = [colmap[col] for col in df.columns]
    df.columns = pd.MultiIndex.from_tuples(tuples, names=headers)

    # Drop any other columns that might have been included in download
    df.drop(['drop_me'], axis=1, level=2, inplace=True)

    return df


def read_entso_e_portal(filepath, url, headers):
    '''Read a file from ENTSO-E into a DataFrame'''
    df = pd.read_excel(
        io=filepath,
        header=9,  # 0 indexed, so the column names are actually in the 10th row
        skiprows=None,
        # create MultiIndex from first 2 columns ['Country', 'Day']
        index_col=[0, 1],
        parse_cols=None,  # None means: parse all columns
        na_values=['n.a.']
    )

    df.columns.names = ['raw_hour']

    # The original data has days and countries in the rows and hours in the
    # columns.  This rearranges the table, mapping hours on the rows and
    # countries on the columns.
    df = df.stack(level='raw_hour').unstack(level='Country').reset_index()

    # Format of the raw_hour-column is normally is 01:00:00, 02:00:00 etc.
    # during the year, but 3A:00:00, 3B:00:00 for the (possibely
    # DST-transgressing) 3rd hour of every day in October, we truncate the
    # hours column after 2 characters and replace letters which are there to
    # indicate the order during fall DST-transition.
    df['hour'] = df['raw_hour'].str[:2].str.replace(
        'A', '').str.replace('B', '')
    # Hours are indexed 1-24 by ENTSO-E, but pandas requires 0-23, so we deduct 1,
    # i.e. the 3rd hour will be indicated by "2:00" rather than "3:00"
    df['hour'] = (df['hour'].astype(int) - 1).astype(str)

    df['timestamp'] = pd.to_datetime(df['Day'] + ' ' + df['hour'] + ':00')
    df.set_index('timestamp', inplace=True)

    # Create a list of daylight savings time (DST)-transitions
    dst_transitions = [
        d.replace(hour=2)
        for d in pytz.timezone('Europe/Berlin')._utc_transition_times
        if d.year >= 2000]

    # Drop 2nd occurence of 3rd hour appearing in October file
    # except for the day of the actual autumn DST-transition.
    df = df[~((df['raw_hour'] == '3B:00:00') & ~
              (df.index.isin(dst_transitions)))]

    # Drop 3rd hour for (spring) DST-transition. October data
    # is unaffected the format is 3A:00:00/3B:00:00.
    df = df[~((df['raw_hour'] == '03:00:00') &
              (df.index.isin(dst_transitions)))]

    df.drop(['Day', 'hour', 'raw_hour'], axis=1, inplace=True)
    df.index = df.index.tz_localize('Europe/Brussels', ambiguous='infer')
    df.index = df.index.tz_convert(None)

    df.rename(columns={'DK_W': 'DK-west', 'UA_W': 'UA-west'}, inplace=True)

    # Create the MultiIndex.
    tuples = [('load', country, 'load', 'ENTSO-E Data Portal', url)
              for country in df.columns]
    df.columns = pd.MultiIndex.from_tuples(tuples, names=headers)

    return df


def read_hertz(filepath, variable_name, url, headers):
    '''Read a file from 50Hertz into a DataFrame'''
    # Since 2016, wind data has an aditional column for offshore.
    # Baltic 1 has been producing since 2011-05-02 and Baltic2 since
    # early 2015 (source: Wikipedia) so it is probably not correct that 50Hertz-Wind
    # data pre-2016 is only onshore. Maybe we can ask at 50Hertz directly.
    if variable_name.split('_')[0] == 'wind':
        tech, attribute, phase = variable_name.split('_')
        tuples = [('wind', 'DE-50hertz', attribute, '50Hertz', url)]
        usecols = [0, 1, 3]

        if phase == 'with-offshore':
            tuples = [('wind', 'DE-50hertz', attribute, '50Hertz', url),
                      ('wind-onshore', 'DE-50hertz', attribute, '50Hertz', url),
                      ('wind-offshore', 'DE-50hertz', attribute, '50Hertz', url)]
            usecols = [0, 1, 3, 4, 5]

    elif variable_name.split('_')[0] == 'solar':
        tech, attribute = variable_name.split('_')
        cols = ['date', 'time', attribute]
        tuples = [('solar', 'DE-50hertz', attribute, '50Hertz', url)]
        usecols = [0, 1, 3]

    df = pd.read_csv(
        filepath,
        sep=';',
        header=3,
        index_col='timestamp',
        names=None,
        parse_dates={'timestamp': ['Datum', 'Von']},
        date_parser=None,
        dayfirst=True,
        decimal=',',
        thousands='.',
        # truncate values in 'time' column after 5th character
        converters={'Von': lambda x: x[:5]},
        usecols=usecols,
    )

    # Until 2006, and in 2015 (except for wind_generation_pre-offshore),
    # during the fall dst-transistion, only the
    # wintertime hour (marked by a B in the data) is reported, the summertime
    # hour, (marked by an A) is missing in the data.
    # dst_arr is a boolean array consisting only of "False" entries, telling
    # python to treat the hour from 2:00 to 2:59 as wintertime.
    if (2006 < pd.to_datetime(df.index.values[0]).year < 2015 or
            (variable_name == 'wind_generation_pre-offshore' and
             pd.to_datetime(df.index.values[0]).year == 2015)):
        df.index = df.index.tz_localize('Europe/Berlin', ambiguous='infer')
    else:
        dst_arr = np.zeros(len(df.index), dtype=bool)
        df.index = df.index.tz_localize('Europe/Berlin', ambiguous=dst_arr)

    df.index = df.index.tz_convert(None)

    # Create the MultiIndex
    df.columns = pd.MultiIndex.from_tuples(tuples, names=headers)

    return df


def read_amprion(filepath, variable_name, url, headers):
    '''Read a file from Amprion into a DataFrame'''
    df = pd.read_csv(
        filepath,
        sep=';',
        header=0,
        index_col='timestamp',
        names=['date', 'time', 'forecast', 'generation'],
        parse_dates={'timestamp': ['date', 'time']},
        date_parser=None,
        dayfirst=True,
        decimal=',',
        thousands=None,
        # Truncate values in 'time' column after 5th character.
        converters={'time': lambda x: x[:5]},
        usecols=[0, 1, 2, 3],
    )

    index1 = df.index[df.index.year <= 2009]
    index1 = index1.tz_localize('Europe/Berlin', ambiguous='infer')

    # In the years after 2009, during the fall dst-transistion, only the
    # summertime hour is reported, the wintertime hour is missing in the data.
    # dst_arr is a boolean array consisting only of "True" entries, telling
    # python to treat the hour from 2:00 to 2:59 as summertime.
    index2 = df.index[df.index.year > 2009]
    dst_arr = np.ones(len(index2), dtype=bool)
    index2 = index2.tz_localize('Europe/Berlin', ambiguous=dst_arr)
    df.index = index1.append(index2)
    df.index = df.index.tz_convert(None)

    # Create the MultiIndex
    tuples = [(variable_name, 'DE-amprion', attribute, 'Amprion', url)
              for attribute in df.columns]
    df.columns = pd.MultiIndex.from_tuples(tuples, names=headers)

    return df


def read_tennet(filepath, variable_name, url, headers):
    '''Read a file from TenneT into a DataFrame'''
    if variable_name == 'solar':
        cols = [0, 1, 2, 3]
        colmap = {'Datum': 'date', 'Position': 'pos', 'prognostiziert [MW]': 'forecast',
                  'tatsächlich [MW]': 'solar'}

    if variable_name == 'wind':
        cols = [0, 1, 2, 3, 4]
        colmap = {'Datum': 'date', 'Position': 'pos', 'prognostiziert [MW]': 'forecast',
                  'tatsächlich [MW]': 'wind', 'Anteil Offshore [MW]': 'wind-offshore'}

    df = pd.read_csv(
        filepath,
        sep=';',
        encoding='latin_1',
        header=3,
        index_col=False,
        names=None,
        parse_dates=False,
        date_parser=None,
        dayfirst=True,
        thousands=None,
        converters=None,
        usecols=cols,
    )

    df = df.rename(columns=colmap)

    df['date'].fillna(method='ffill', limit=100, inplace=True)

    # Check the rows for irregularities
    for i in range(len(df.index)):
        # On the day in March when summertime begins, shift the data forward by
        # 1 hour, beginning with the 9th quarter-hour, so the index runs again
        # up to 96
        if (df['pos'][i] == 92 and ((i == len(df.index) - 1) or (df['pos'][i + 1] == 1))):
            slicer = df[(df['date'] == df['date'][i]) & (df['pos'] >= 9)].index
            df.loc[slicer, 'pos'] = df['pos'] + 4

        if df['pos'][i] > 96:  # True when summertime ends in October
            logger.debug('%s th quarter-hour at %s, position %s',
                         df['pos'][i], df.ix[i, 'date'], (i))

            # Instead of having the quarter-hours' index run up to 100, we want
            # to have it set back by 1 hour beginning from the 13th
            # quarter-hour, ending at 96
            if df['pos'][i] == 100 and not (df['pos'] == 101).any():
                slicer = df[(df['date'] == df['date'][i])
                            & (df['pos'] >= 13)].index
                df.loc[slicer, 'pos'] = df['pos'] - 4

    # Compute timestamp from position and generate datetime-index
    df['hour'] = (np.trunc((df['pos'] - 1) / 4)).astype(int).astype(str)
    df['minute'] = (((df['pos'] - 1) % 4) * 15).astype(int).astype(str)
    df['timestamp'] = pd.to_datetime(df['date'] + ' ' + df['hour'] + ':' +
                                     df['minute'], dayfirst=True)
    df.set_index('timestamp', inplace=True)

    df.drop(['pos', 'date', 'hour', 'minute'], axis=1, inplace=True)

    df.index = df.index.tz_localize('Europe/Berlin', ambiguous='infer')
    df.index = df.index.tz_convert(None)

    # Create the MultiIndex
    if variable_name == 'solar':
        tuples = [('solar', 'DE-tennet', 'forecast', 'TenneT', url),
                  ('solar', 'DE-tennet', 'generation', 'TenneT', url)]
    if variable_name == 'wind':  # offshore generation starts 2009-09-20
        tuples = [('wind', 'DE-tennet', 'forecast', 'TenneT', url),
                  ('wind', 'DE-tennet', 'generation', 'TenneT', url),
                  ('wind-offshore', 'DE-tennet', 'generation', 'TenneT', url)]
    df.columns = pd.MultiIndex.from_tuples(tuples, names=headers)

    return df


def read_transnetbw(filepath, variable_name, url, headers):
    '''Read a file from TransnetBW into a DataFrame'''
    df = pd.read_csv(
        filepath,
        sep=';',
        header=0,
        index_col='timestamp',
        names=['date', 'time', 'forecast', 'generation'],
        parse_dates={'timestamp': ['date', 'time']},
        date_parser=None,
        dayfirst=True,
        decimal=',',
        thousands=None,
        converters=None,
        usecols=[2, 3, 4, 5],  # 0-indexed, i.e. "2" refers to the 3rd column
    )

    # 'ambigous' refers to how the October dst-transition hour is handled.
    # ‘infer’ will attempt to infer dst-transition hours based on order.
    df.index = df.index.tz_localize('Europe/Berlin', ambiguous='infer')
    df.index = df.index.tz_convert(None)

    # The 2nd column represents the start and the 4th the end of the respective
    # period. The former has some errors, so we use the latter to construct the
    # index and shift the data back by 1 period.
    df = df.shift(periods=-1, freq='15min', axis='index')

    # Create the MultiIndex
    tuples = [(variable_name, 'DE-transnetbw', attribute, 'TransnetBW', url)
              for attribute in df.columns]
    df.columns = pd.MultiIndex.from_tuples(tuples, names=headers)

    return df


def read_opsd(filepath, url, headers):
    '''Read a file from OPSD into a DataFrame'''
    df = pd.read_csv(
        filepath,
        sep=',',
        header=0,
        index_col='timestamp',
        names=None,
        parse_dates={'timestamp': ['day']},
        date_parser=None,
        dayfirst=False,
        decimal='.',
        thousands=None,
        converters=None,
        usecols=None
    )

    # Translate columns
    cap_DE = 'BNetzA and Netztransparenz.de'
    colmap = {
        'Solar': ('solar', 'DE', 'capacity', cap_DE, url),
        'Onshore': ('wind-onshore', 'DE', 'capacity', cap_DE, url),
        'Offshore': ('wind-offshore', 'DE', 'capacity', cap_DE, url)
    }

    # Drop any column not in colmap
    df = df[list(colmap.keys())]

    # The capacities data only has one entry per day, which pandas
    # interprets as 00:00h. We will broadcast the dayly data for
    # all quarter-hours of the day until the next given data point.
    # For this, we we expand the index so it reaches to 23:59 of
    # the last day, not only 00:00.
    last = pd.to_datetime([df.index[-1].replace(hour=23, minute=59)])
    until_last = df.index.append(last).rename('timestamp')
    df = df.reindex(index=until_last, method='ffill')
    df.index = df.index.tz_localize('Europe/Berlin')
    df.index = df.index.tz_convert(None)
    df = df.resample('15min').ffill()

    # Create the MultiIndex
    tuples = [colmap[col] for col in df.columns]
    df.columns = pd.MultiIndex.from_tuples(tuples, names=headers)

    return df


def read_svenska_kraftnaet(filePath, variable_name, url, headers):
    '''Read a file from Svenska Kraftnät into a DataFrame'''
    if variable_name in ['wind_solar_1', 'wind_solar_2']:
        skip = 4
        cols = [0, 1, 3]
        colnames = ['date', 'hour', 'wind']
    else:
        if variable_name == 'wind_solar_4':
            skip = 5
        else:
            skip = 7
        cols = [0, 2, 8]
        colnames = ['timestamp', 'wind', 'solar']

    df = pd.read_excel(
        io=filePath,
        # read the last sheet (in some years,
        # there are hidden sheets that would cause errors)
        sheetname=-1,
        header=None,
        skiprows=skip,
        index_col=None,
        parse_cols=cols
    )

    df.columns = colnames

    if variable_name in ['wind_solar_1', 'wind_solar_2']:
        # in 2009 there is a row below the table for the sums that we don't
        # want to read in
        df = df[df['date'].notnull()]
        df['timestamp'] = pd.to_datetime(
            df['date'].astype(int).astype(str) + ' ' +
            df['hour'].astype(int).astype(str).str.replace('00', '') + ':00',
            dayfirst=False,
            infer_datetime_format=True)
        df.drop(['date', 'hour'], axis=1, inplace=True)
    else:
        # in 2011 there is a row below the table for the sums that we don't
        # want to read in
        df = df[((df['timestamp'].notnull()) &
                 (df['timestamp'].astype(str) != 'Tot summa GWh'))]
        df['timestamp'] = pd.to_datetime(df['timestamp'], dayfirst=True)

    df.set_index('timestamp', inplace=True)
    # The timestamp ("Tid" in the original) gives the time without
    # daylight savings time adjustments (normaltid). To convert to UTC,
    # one hour has to be deducted
    df.index = df.index + pd.offsets.Hour(-1)

    # Create the MultiIndex
    tuples = [(tech, 'SE', 'generation', 'Svenska Kraftnaet', url)
              for tech in df.columns]
    df.columns = pd.MultiIndex.from_tuples(tuples, names=headers)

    return df


def read(source_name, variable_name, url, res_key, headers,
         out_path='original_data', start_from_user=None, end_from_user=None):
    """
    For the sources specified in the sources.yml file, pass each downloaded
    file to the correct read function.

    Parameters
    ----------
    source_name : str
        Name of source to read files from
    variable_name : str
        Indicator for subset of data available together in the same files
    url : str
        URL of the Source to be placed in the column-MultiIndex
    res_key : str
        Resolution of the source data. Must be one of ['15min', '60min']
    headers : list
        List of strings indicating the level names of the pandas.MultiIndex
        for the columns of the dataframe
    out_path : str, default: 'original_data'
        Base download directory in which to save all downloaded files
    start_from_user : datetime.date, default None
        Start of period for which to read the data
    end_from_user : datetime.date, default None
        End of period for which to read the data

    Returns
    ----------
    data_set: pandas.DataFrame
        A DataFrame containing the combined data for variable_name 

    """
    data_set = pd.DataFrame()

    variable_dir = os.path.join(out_path, source_name, variable_name)

    logger.info('reading %s - %s', source_name, variable_name)

    files_existing = sum([len(files) for r, d, files in os.walk(variable_dir)])
    files_success = 0

    # Check if there are folders for variable_name
    if not os.path.exists(variable_dir):
        logger.warning('folder not found for %s, %s',
                       source_name, variable_name)
        return data_set

    # For each file downloaded for that variable
    for container in os.listdir(variable_dir):
        # Skip this file if period covered excluded by user
        if start_from_user:
            # Filecontent is too old
            if start_from_user > yaml.load(container.split('_')[1]):
                continue  # go to next container

        if end_from_user:
            # Filecontent is too recent
            if end_from_user < yaml.load(container.split('_')[0]):
                continue  # go to next container

        files = os.listdir(os.path.join(variable_dir, container))

        # Check if there is only one file per folder
        if len(files) == 0:
            logger.warning('found no file in %s %s %s',
                           source_name, variable_name, container)
            continue

        elif len(files) > 1:
            logger.warning('found more than one file in %s %s %s',
                           source_name, variable_name, container)
            continue

        filepath = os.path.join(variable_dir, container, files[0])

        # Check if file is not empty
        if os.path.getsize(filepath) < 128:
            logger.warning('%s \n file is smaller than 128 Byte, which means it is probably empty',
                           filepath)
        else:
            logger.debug('reading data:\n\t '
                         'Source:   %s\n\t '
                         'Variable: %s\n\t '
                         'Filename: %s',
                         source_name, variable_name, files[0])

            update_progress(files_success, files_existing)

            if source_name == 'OPSD':
                data_to_add = read_opsd(filepath, url, headers)
            elif source_name == 'CEPS':
                data_to_add = read_ceps(filepath, variable_name, url, headers)
            elif source_name == 'ENTSO-E Data Portal':
                #save_stdout = sys.stdout
                #sys.stdout = open('trash', 'w')
                data_to_add = read_entso_e_portal(filepath, url, headers)
                #sys.stdout = save_stdout
            elif source_name == 'Energinet.dk':
                data_to_add = read_energinet_dk(filepath, url, headers)
            elif source_name == 'Elia':
                data_to_add = read_elia(filepath, variable_name, url, headers)
            elif source_name == 'PSE':
                data_to_add = read_pse(filepath, variable_name, url, headers)
            elif source_name == 'RTE':
                data_to_add = read_rte(filepath, variable_name, url, headers)
            elif source_name == 'Svenska Kraftnaet':
                data_to_add = read_svenska_kraftnaet(
                    filepath, variable_name, url, headers)
            elif source_name == '50Hertz':
                data_to_add = read_hertz(filepath, variable_name, url, headers)
            elif source_name == 'Amprion':
                data_to_add = read_amprion(
                    filepath, variable_name, url, headers)
            elif source_name == 'TenneT':
                data_to_add = read_tennet(
                    filepath, variable_name, url, headers)
            elif source_name == 'TransnetBW':
                data_to_add = read_transnetbw(
                    filepath, variable_name, url, headers)

            if data_set.empty:
                data_set = data_to_add
            else:
                data_set = data_set.combine_first(data_to_add)

            files_success += 1
            update_progress(files_success, files_existing)

    if data_set.empty:
        logger.warning('returned empty DataFrame for %s, %s',
                       source_name, variable_name)
        return data_set

    # Reindex with a new index that is sure to be continous in order to later
    # expose gaps in the data.
    no_gaps = pd.DatetimeIndex(start=data_set.index[0],
                               end=data_set.index[-1],
                               freq=res_key)
    data_set = data_set.reindex(index=no_gaps)

    # Cut off the data outside of [start_from_user:end_from_user]
    # First, convert userinout to UTC time
    if start_from_user:
        start_from_user = (
            pytz.timezone('Europe/Brussels')
            .localize(datetime.combine(start_from_user, time()))
            .astimezone(pytz.timezone('UTC')))

    if end_from_user:
        end_from_user = (
            pytz.timezone('Europe/Brussels')
            .localize(datetime.combine(end_from_user, time()))
            .astimezone(pytz.timezone('UTC'))) - timedelta(minutes=int(res_key[:2]))

    # Then cut off the data_set
    data_set = data_set.loc[start_from_user:end_from_user, :]

    return data_set


def update_progress(count, total):
    '''
    Display or updates a console progress bar.

    Parameters
    ----------
    count : int
        number of files that have been read so far
    total : int
        total number aif files

    Returns
    ----------
    None

    '''

    barLength = 50  # Modify this to change the length of the progress bar
    status = ""
    progress = count / total
    if isinstance(progress, int):
        progress = float(progress)
    if progress >= 1:
        progress = 1
        status = "Done...\r\n"
    block = int(round(barLength * progress))
    text = "\rProgress: [{0}] {1}/{2} files {3}".format(
        "#" * block + "-" * (barLength - block), count, total, status)
    sys.stdout.write(text)
    sys.stdout.flush()

    return
