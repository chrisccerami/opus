###############################################
#
#   search.views
#
################################################
import sys
import hashlib
from operator import __or__ as OR
import julian
import json
from pyparsing import ParseException
from django.conf import settings
from django.db.models import Q
from django.apps import apps
from django.db.models.sql.datastructures import EmptyResultSet
from django.db import connection, DatabaseError
from django.core.cache import cache

"""
from tools.app_utils import *
from metadata.views import *
"""
from search.models import *
from tools.app_utils import stripNumericSuffix, sortDict
from paraminfo.models import ParamInfo
import metadata.views

import logging
log = logging.getLogger(__name__)


def get_param_info_by_slug(slug):
    slug_no_num = stripNumericSuffix(slug)

    try:
        return ParamInfo.objects.get(slug=slug_no_num)
    except ParamInfo.DoesNotExist:
        try:
            return ParamInfo.objects.get(slug=slug)  #  qtypes for ranges come through as the param_name_no num which doesn't exist in param_info, so grab the param_info for the lower side of hte ragne
        except ParamInfo.DoesNotExist:
            try:
                return ParamInfo.objects.get(slug=slug + '1')  #  qtypes for ranges come through as the param_name_no num which doesn't exist in param_info, so grab the param_info for the lower side of hte ragne
                # this is not a query param, ignore it
            except ParamInfo.DoesNotExist:
                return False

def get_param_info_by_param(param_name):
    cat_name      = param_name.split('.')[0]
    name          = param_name.split('.')[1]

    try:
        return ParamInfo.objects.get(category_name=cat_name, name=name)
    except ParamInfo.DoesNotExist:
        # single column range queries will not have the numeric suffix
        try:
            name_no_num = stripNumericSuffix(name)
            return ParamInfo.objects.get(category_name=cat_name, name=name_no_num)
        except ParamInfo.DoesNotExist:
            return False

def is_single_column_range(param_name):
    cat_name      = param_name.split('.')[0]
    name          = param_name.split('.')[1]

    try:
        param_info = ParamInfo.objects.get(category_name=cat_name, name=name)
        return False
    except ParamInfo.DoesNotExist:
        # single column range queries will not have the numeric suffix
        try:
            name_no_num = stripNumericSuffix(name)
            return ParamInfo.objects.get(category_name=cat_name, name=name_no_num)
        except ParamInfo.DoesNotExist:
            return False


def constructQueryString(selections, extras):

    all_qtypes = extras['qtypes'] if 'qtypes' in extras else []
    # keeping track of some things
    long_queries = []  # special longitudinal queries are pure sql
    string_queries = []  # special handling for string queries ugh!
    q_objects = []  # for building up the query object
    finished_ranges = []  # ranges are done for both sides at once.. so track which are finished to avoid duplicates

    # buld the django query
    from metadata.views import getMultName  # avoids circular import issue
    for param_name, value_list in selections.items():

        # lookup info about this param_name
        param_name_no_num = stripNumericSuffix(param_name)  # this is used later for other things!
        cat_name = param_name.split('.')[0]
        cat_model_name = ''.join(cat_name.lower().split('_'))
        name = param_name.split('.')[1]
        param_info = get_param_info_by_param(param_name)
        if not param_info:
            return False

        form_type = param_info.form_type
        special_query = param_info.special_query

        # define any qtypes for this param_name from query
        qtypes = all_qtypes[param_name_no_num] if param_name_no_num in all_qtypes else []

        # now build the q_objects to run the query, by form_type:

        # MULTs
        if form_type in settings.MULT_FORM_TYPES:
            mult_name = getMultName(param_name)
            model_name = mult_name.title().replace('_','')
            model = apps.get_model('search',model_name)
            mult_values = [x['pk'] for x in list(model.objects.filter(Q(label__in=value_list) | Q(value__in=value_list) ).values('pk'))]
            if cat_name != 'obs_general':
                q_objects.append(Q(**{"%s__%s__in" % (cat_model_name, mult_name): mult_values }))
            else:
                q_objects.append(Q(**{"%s__in" % mult_name: mult_values }))

        # RANGE
        if form_type in settings.RANGE_FIELDS:

            # this prevents range queries from getting through twice
            # if one range side has been processed can skip the 2nd, it gets done when the 1st is
            if param_name_no_num in finished_ranges:
                # this range has already been done, skip to next param in the loop
                continue

            finished_ranges += [param_name_no_num]

            # longitude queries
            if special_query == 'long':
                # this parameter requires a longitudinal query
                # these are crazy sql and can't use Django's model interface
                # so after converting the rest of the query params from django model
                # statements to sql these are tacked on at the end
                # both sides of range must be defined by user for this to work
                if selections[param_name_no_num + '1'] and selections[param_name_no_num + '2']:
                    lq, lq_params = longitudeQuery(selections,param_name)
                    long_queries.append((lq, lq_params))

                else:
                    raise ValidationError


            else:
                # get the range query object and append it to the query
                q_obj = range_query_object(selections, param_name, qtypes)

                q_objects.append(q_obj)


        # STRING
        if form_type == 'STRING':
            q_obj = string_query_object(param_name, value_list, qtypes)
            q_objects.append(q_obj)

    # construct our query, we'll be breaking into raw sql, but for that
    # we'll be using the sql django generates through its model interface
    try:
        sql, params = ObsGeneral.objects.filter(*q_objects).values('pk').query.sql_with_params()

        # append any longitudinal queries to the query string
        if long_queries:

            params = list(params)

            # q += " ".join([" and (%s) " % long_query for long_query in long_queries])
            if 'where' in sql.lower():
                sql = sql + ' AND obs_general.id in '
            else:
                sql = sql + ' where obs_general.id in '


            sql = sql + ' AND obs_general.id in '.join([" (%s) " % long_query[0] for long_query in long_queries])
            for long_q in long_queries:
                params += list(long_query[1])

            params = tuple(params)

        return sql, params

    except EmptyResultSet:
        return False



def getUserQueryTable(selections=None, extras=None):
    """
    This is THE main data query place.  Performs a data search and creates
    a table of Ids that match the result rows.

    (the function urlToSearchParams take the user http request object and
    creates the data objects that are passed to this function)

    """
    cursor = connection.cursor()

    if not bool(extras):
        extras = {}
    if not bool(selections):
        selections = {}

    # do we have a cache key
    no     = setUserSearchNo(selections,extras)
    ptbl   = metadata.views.getUserSearchTableName(no)

    # is this key set in memcached
    cache_key = 'cache_table:' + str(no)

    if (cache.get(cache_key)):
        return cache.get(cache_key)

    # it could still exist in database
    try:
        cursor.execute("desc cache_%s" % str(no))
        cache.set(cache_key,ptbl)
        return 'cache_%s' % str(no)

    except DatabaseError:
        pass  # no table is there, we go on to build it below

    ## cache table dose not exist, we will make one by doing some data querying:
    try:
        sql, params = constructQueryString(selections, extras)
    except TypeError:
        log.debug('TypeError, constructQueryString returned False')
        return False

    if not sql:
        log.debug('getUserQueryTable - query string was empty ')
        return False

    try:
        # with this we can create a table that contains the single row
        cursor.execute("create table " + connection.ops.quote_name(ptbl) + ' ' + sql, tuple(params))
        # add the key **** this, and perhaps the create statement too, can be spawned to a backend process ****
        cursor.execute("alter table " + connection.ops.quote_name(ptbl) + " add unique key(id)  ")

        cache.set(cache_key,ptbl)
        return ptbl

    except DatabaseError:
        e = sys.exc_info()[1]
        if 'exists' in e.lower():
            return ptbl
        log.error('query execute failed: create/alter table ')
        log.error(sys.exc_info()[1])
        return False



def urlToSearchParams(request_get):
    """
    OPUS lets users put nice readable things in the URL, like "planet=Jupiter" rather than "planet_id=3"
    this function takes the url params and translates it into a list that contains 2 dictionaries
    the first dict is the user selections: keys of the dictionary are param_names of data columns in
    the data table values are always lists and represent the users selections
    the 2nd dict is any extras being passed by user, like qtypes that define what types of queries
    will be performed for each param-value set in the first dict

    NOTE: pass request_get = request.GET to this func please
    (this func doesn't return an http response so unit tests freak if you pass it an http request :)

    example command line usage:

    >>>> from search.views import *
    >>>> from django.http import QueryDict
    >>>> q = QueryDict("planet=Saturn")
    >>>> (selections,extras) = urlToSearchParams(q)
    >>>> selections
    {'planet_id': [u'Jupiter']}
    >>>> extras
    {'qtypes': {}}

    """
    selections = {}
    qtypes     = {}

    for searchparam in request_get.items():
        # try:
        slug = searchparam[0]
        slug_no_num = stripNumericSuffix(slug)
        values = searchparam[1].strip(',').split(',')

        qtype = False  # assume this is not a qtype statement
        if slug.find('qtype') == 0:
            qtype = True  # this is a statement of query type!
            slug = slug.split('-')[1]
            slug_no_num = stripNumericSuffix(slug)

        param_info = get_param_info_by_slug(slug)
        if not param_info:
            continue

        param_name = param_info.param_name()
        form_type = param_info.form_type

        param_name_no_num = stripNumericSuffix(param_name)

        if qtype:
            qtypes[param_name_no_num] = request_get.get('qtype-'+slug_no_num,False).strip(',').split(',')
            continue

        if form_type in settings.MULT_FORM_TYPES:
            # mult form types can be sorted to save duplicate queries being built
            selections[param_name] = sorted(searchparam[1].strip(',').split(','))

        else:
            # no other form types can be sorted since their ordering corresponds to qtype ordering
            if searchparam[1]:  # if it has a value
                if form_type == "RANGE":
                    if param_name == param_name_no_num:
                        # this is a single column range query
                        ext = slug[-1]
                        selections[param_name + ext] = map(float, values)
                    else:
                        # normal 2-column range query
                        selections[param_name] = map(float, values)
                else:
                    selections[param_name] = values

        # except: pass # the param passed doesn't exist or is a USER PREF AAAAAACK

    if len(selections.keys()) > 0:
        extras  = {}
        extras['qtypes'] = qtypes
        results = []
        results.append(selections)
        results.append(extras)

        return results

    else:
        return [{}, {}]


def setUserSearchNo(selections=None,extras=None):
    """
    creates a new row in userSearches model for every search request
    [cleanup,optimize]
    this table (model) lists query params+values plus any extra info needed to run a data search query
    this method looks in user_searches table for current selections
    if none exist creates it, returns id key
    """
    if not bool(extras): extras = {}

    if not bool(selections): selections = {}

    qtypes_json = qtypes_hash = None
    if 'qtypes' in extras:
        # 'any' is the default qtype, so lets not set that in the cache, set 'any' = None
        for k,qlist in extras['qtypes'].items():
            extras['qtypes'][k] = [x if x != 'any' else None for x in qlist]
            if len(extras['qtypes'][k])==1 and extras['qtypes'][k][0]==None:
                extras['qtypes'].pop(k)
        if len(extras['qtypes']):
            qtypes_json = str(json.dumps(sortDict(extras['qtypes'])))
            qtypes_hash = hashlib.md5(qtypes_json).hexdigest()

    units_json = units_hash = None
    if 'units' in extras:
        units_json = str(json.dumps(sortDict(extras['units'])))
        units_hash = hashlib.md5(units_json).hexdigest()

    string_selects_json = string_selects_hash = None
    if 'string_selects' in extras:
        string_selects_json = str(json.dumps(sortDict(extras['string_selects'])))
        string_selects_hash = hashlib.md5(string_selects_json).hexdigest()


    selections_json = str(json.dumps(selections))
    selections_hash = hashlib.md5(selections_json).hexdigest()

    # do we already have this cached?
    cache_key = 'usersearchno:selections_hash:' + str(selections_hash) + ':qtypes_hash:' +  str(qtypes_hash) + ':units_hash:' + str(units_hash) + ':string_selects_hash:' + str(string_selects_hash)
    if (cache.get(cache_key)):
        return cache.get(cache_key)

    # no cache, let's keep going..
    try:
        s = UserSearches.objects.get(selections_hash=selections_hash,qtypes_hash=qtypes_hash,units_hash=units_hash,string_selects_hash=string_selects_hash)
    except UserSearches.MultipleObjectsReturned:
        s = UserSearches.objects.filter(selections_hash=selections_hash,qtypes_hash=qtypes_hash,units_hash=units_hash,string_selects_hash=string_selects_hash)[0]
    except UserSearches.DoesNotExist:
        s = UserSearches(selections_hash=selections_hash, selections_json=selections_json, qtypes=qtypes_json,qtypes_hash=qtypes_hash,units=units_json,units_hash=units_hash, string_selects=string_selects_json,string_selects_hash=string_selects_hash )
        s.save()

    cache.set(cache_key,s.id)

    return s.id


def string_query_object(param_name, value_list, qtypes):

    model_name = param_name.split('.')[0].lower().replace('_','')

    if model_name == 'obsgeneral':
        param_model_name = param_name.split('.')[1]
    else:
        param_model_name = model_name + '__' + param_name.split('.')[1]

    for key,value in enumerate(value_list):

        qtype = qtypes[key] if key in qtypes else 'contains'

        if qtype == 'contains':

            q_exp = Q(**{"%s__icontains" % param_model_name: value })
            pass

        if qtype == 'begins':
            q_exp = Q(**{"%s__startswith" % param_model_name: value })
            pass

        if qtype == 'ends':
            q_exp = Q(**{"%s__endswith" % param_model_name: value })
            pass

        if qtype == 'matches':
            q_exp = Q(**{"%s" % param_model_name: value })
            pass

        if qtype == 'excludes':
            q_exp = ~Q(**{"%s__icontains" % param_model_name: value })
            pass

    return q_exp

def range_query_object(selections, param_name, qtypes):
    """
    builds query for numeric ranges where 2 data columns represent min and max values
    any all only
    any / all / only

    """
    # grab some info about this param
    param_info = get_param_info_by_param(param_name)
    if not param_info:
        return False

    form_type     = param_info.form_type
    table_name = param_info.category_name

    # we will define both sides of the query, so define those param names
    param_name_no_num = stripNumericSuffix(param_name)
    param_name_min = param_name_no_num + '1'
    param_name_max = param_name_no_num + '2'

    # grab min and max values from query selections object
    values_min = selections[param_name_min] if param_name_min in selections else []
    values_max = selections[param_name_max] if param_name_max in selections else []

    # but, for constructing the query,
    # if this is a single column range, the param_names are both the same
    if is_single_column_range(param_name):
        param_name_min = param_name_max = param_name_no_num

    # to follow related models, we need the lowercase model name, not the param name
    # UNLESS this param is in the obs_General table, then must leave out the model name!
    if table_name == 'obs_general':
        param_model_name_min = param_name_min.split('.')[1]
        param_model_name_max = param_name_max.split('.')[1]
    else:
        param_model_name_min = table_name.lower().replace('_','') + '__' + param_name_min.split('.')[1]
        param_model_name_max = table_name.lower().replace('_','') + '__' + param_name_max.split('.')[1]

    # if these are times convert values from time string to seconds
    if form_type == 'TIME':
        values_min = convertTimes(values_min)

        try:
            index = values_min.index(None)
            raise Exception("InvalidTimes")
        except: pass
        values_max = convertTimes(values_max)
        try:
            index = values_max.index(None)
            raise Exception("InvalidTimes")
        except: pass

    qtype = qtypes[0] if qtypes else ['any']

    # we need to know how many times to go through this loop
    count = len(values_max) if len(values_max) > len(values_min) else len(values_min) # how many times to go thru this loop:

    # now collect the query expressions
    all_query_expressions = []  # these will be joined by OR
    i=0
    while i < count:

        # define some things
        value_min, value_max, q_type = None, None, qtype
        try: value_min = values_min[i]
        except IndexError: pass

        try: value_max = values_max[i]
        except IndexError: pass

        try: qtype = qtypes[i]
        except IndexError: pass

        # reverse value_min and value_max if value_min < value_max
        if value_min is not None and value_max is not None:
            (value_min,value_max) = sorted([value_min,value_max])

        # we should end up with 2 query expressions
        q_exp, q_exp1, q_exp2 = None, None, None

        if qtype == 'all':

            if value_min:
                # param_name_min <= value_min
                q_exp1 = Q(**{"%s__lte" % param_model_name_min: value_min })

            if value_max:
                # param_name_max >= value_max
                q_exp2 = Q(**{"%s__gte" % param_model_name_max: value_max })

        elif qtype == 'only':

            if value_min:
                # param_name_min >= value_min
                q_exp1 = Q(**{"%s__gte" % param_model_name_min: value_min })

            if value_max:
                # param_name_max <= value_max
                q_exp2 = Q(**{"%s__lte" % param_model_name_max: value_max })

        else: # defaults to qtype = any
            if value_max:
                # param_name_min <= value_max
                q_exp1 = Q(**{"%s__lte" % param_model_name_min: value_max })

            if value_min:
                # param_name_max >= value_min
                q_exp2 = Q(**{"%s__gte" % param_model_name_max: value_min })

        # put the query expressions together as "&" queries
        if q_exp1 and q_exp2:
            q_exp = q_exp1 & q_exp2
        elif q_exp1:
            q_exp = q_exp1
        elif q_exp2:
            q_exp = q_exp2

        all_query_expressions.append(q_exp)
        i+=1


    # now we have all query expressions, join them with 'OR'
    return reduce(OR, all_query_expressions)


def longitudeQuery(selections,param_name):
    # raises 'KeyError' or IndexError if min or max value is blank
    # or ranges are lopsided, all ranges for LONG query must have both sides
    # defined returns string sql

    clauses = []  # we may have a number of clauses to piece together
    params  = []  # we are building a sql string

    cat_name = param_name.split('.')[0]
    name = param_name.split('.')[1]
    name_no_num = stripNumericSuffix(name)
    param_name_no_num = stripNumericSuffix(param_name)
    param_name_min = param_name_no_num + '1'
    param_name_max = param_name_no_num + '2'
    col_d_long = cat_name + '.d_' + name_no_num

    values_min = selections[param_name_min]
    values_max = selections[param_name_max]

    if len(values_min) != len(values_max):
        raise KeyError

    count = len(values_max)
    i=0
    while i < count:

        value_min = values_min[i]
        value_max = values_max[i]

        # find the midpoint and dx of the user's range
        if (value_max >= value_min):
            longit = (value_min + value_max)/2.
            d_long = longit - value_min
        else:
            longit = (value_min + value_max + 360.)/2.
            d_long = longit - value_min

        if (longit >= 360): longit = longit - 360.

        if d_long:
            clauses += ["(abs(abs(mod(%s - " + param_name_no_num + " + 180., 360.)) - 180.) <= %s + " + col_d_long + ")"];
            params  += [longit,d_long]

        i+=1

    clause = ' OR '.join(clauses)

    table_name = param_name_no_num.split('.')[0]

    key_field = 'obs_general_id' if cat_name != 'obs_general' else 'obs_general.id'

    query = "select " + key_field + " from " + table_name + " where " + clause

    return query, tuple(params)


def convertTimes(value_list):
    """ other conversion scripts are 'seconds_to_time','seconds_to_et' """
    converted = []
    for time in value_list:
        try:
            (day, sec, timetype) = julian.day_sec_type_from_string(time)
            time_sec = julian.tai_from_day(day) + sec
            converted += [time_sec]
        except ParseException:
            logging.debug("could not convert time " + time)
            converted += [None]
    return converted
