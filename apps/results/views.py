################################################
#
#   results.views
#
################################################
import settings
import json
import csv
from django.template import loader, Context
from django.http import Http404
from django.shortcuts import render
from collections import OrderedDict as SortedDict
from django.db import connection, DatabaseError
from django.apps import apps
from django.core.exceptions import FieldError
from search.views import *
from search.models import *
from results.models import *
from paraminfo.models import *
from metadata.views import *
from user_collections.views import *
from tools.app_utils import *
from metrics.views import update_metrics
from django.views.decorators.cache import never_cache

import logging
log = logging.getLogger(__name__)

def get_csv(request, fmt=None):
    """
        creates csv
        only works right now for a collection
        defaults to response object
        or as first line and all data tuple object for fmt=raw
    """
    slugs = request.GET.get('cols')
    all_data = getPage(request, colls=True, colls_page='all')

    if fmt == 'raw':
        return slugs.split(","), all_data[2]
    else:
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="data.csv"'
        wr = csv.writer(response)
        wr.writerow(slugs.split(","))
        wr.writerows(all_data[2])
        return response

def get_all_categories(request, ring_obs_id):
    """ returns list of all cateories this ring_obs_id apepars in """
    all_categories = []
    table_info = TableName.objects.all().values('table_name', 'label').order_by('disp_order')

    for tbl in table_info:  # all tables
        table_name = tbl['table_name']
        if table_name == 'obs_surface_geometry':
            # obs_surface_geometry is not a data table
            # it's only used to select targets, not to hold data, so remove it
            continue

        label = tbl['label']
        model_name = ''.join(table_name.title().split('_'))

        try:
            table_model = apps.get_model('search', model_name)
        except LookupError:
            continue  # oops some models don't actually exist

        # are not ring_obs_id unique in all obs tables so why is this not a .get query
        results = table_model.objects.filter(ring_obs_id=ring_obs_id).values('ring_obs_id')
        if results:
            cat = {'table_name': table_name, 'label': label}
            all_categories.append(cat)

    return HttpResponse(json.dumps(all_categories), content_type="application/json")


def category_list_http_endpoint(request):
    """ returns a list of triggered categories (table_names) and labels
        as json response
        for use as part of public http api """
    if request and request.GET:
        try:
            (selections,extras) = urlToSearchParams(request.GET)
        except TypeError:
            selections = None
    else:
        selections = None

    if not selections:
        triggered_tables = settings.BASE_TABLES[:]  # makes a copy of settings.BASE_TABLES
    else:
        triggered_tables = get_triggered_tables(selections, extras)

    # the main geometry table, obs_surface_geometry, is not table that holds results data
    # it is only there for selecting targets, which then trigger the other geometry tables.
    # so in the context of returning list of categories it gets removed..
    try:
        triggered_tables.remove('obs_surface_geometry')
    except ValueError:
        pass  # it wasn't in there so no worries

    labels = TableName.objects.filter(table_name__in=triggered_tables).values('table_name','label').order_by('disp_order')

    return HttpResponse(json.dumps([ob for ob in labels]), content_type="application/json")


def getData(request,fmt):
    update_metrics(request)
    """
    a page of results for a given search
    """
    if not request.session.get('has_session'):
        request.session['has_session'] = True

    session_id = request.session.session_key

    [page_no, limit, page, page_ids, order] = getPage(request)

    checkboxes = True if (request.is_ajax()) else False

    slugs = request.GET.get('cols',settings.DEFAULT_COLUMNS)
    if not slugs: slugs = settings.DEFAULT_COLUMNS

    is_column_chooser = request.GET.get('col_chooser', False)

    labels = []
    id_index = 0

    for slug in slugs.split(','):
        if slug == 'ringobsid':
            id_index = slugs.split(',').index(slug)
        try:
            labels += [ParamInfo.objects.get(slug=slug).label_results]
        except ParamInfo.DoesNotExist:
            # this slug doens't match anything in param info, nix it
            if '1' in slug:
                # single column range slugs will not have the index, but
                # will come in with it because of how ui is designed, so
                # look for the slug without the index
                temp_slug = slug[:-1]
                try:
                    labels += [ParamInfo.objects.get(slug=temp_slug).label_results]
                except ParamInfo.DoesNotExist:
                    log.error('could not find param_info for ' + slug)
                    continue

    if is_column_chooser:
        labels.insert(0, "add")   # adds a column for checkbox add-to-collections

    collection = ''
    if request.is_ajax():
        # find the members of user collection in this page
        # for pre-filling checkboxes
        collection = get_collection_in_page(page, session_id)

    data = {'page_no':page_no, 'limit':limit, 'page':page, 'count':len(page), 'labels': labels}

    if fmt == 'raw':
        return data
    else:
        return responseFormats(data,fmt,template='data.html', id_index=id_index, labels=labels,checkboxes=checkboxes, collection=collection, order=order)

def get_slug_categories(request, slugs):
    slugs = request.GET.get('cols', False)

    if not slugs:
        raise Http404

    all_cats = {}

    for slug in slugs:
        param_info = get_param_info_by_slug(slug)
        all_cats.append(param_info.category_name)
        params_by_table.setdefault(table_name, []).append(param_info.param_name())
        all_info[slug] = param_info  # to get things like dictionary entries for interface

def get_metadata_by_slugs(request, ring_obs_id, slugs, fmt):
    """
    returns results for specified slugs
    """
    update_metrics(request)

    params_by_table = {}  # params by table_name
    data = []
    all_info = {}

    for slug in slugs:
        param_info = get_param_info_by_slug(slug)
        if not param_info:
            continue  # todo this should raise end user error
        table_name = param_info.category_name
        params_by_table.setdefault(table_name, []).append(param_info.param_name().split('.')[1])
        all_info[slug] = param_info  # to get things like dictionary entries for interface

    if slugs and not all_info:
        # none of the slugs were valid slugs
        # can't ignore them and return all metadata because can lead to infinite recursion here
        raise Http404

    for table_name, param_list in params_by_table.items():
        model_name = ''.join(table_name.title().split('_'))
        table_model = apps.get_model('search', model_name)

        results = table_model.objects.filter(ring_obs_id=ring_obs_id).values(*param_list)
                  # are not ring_obs_id unique in all obs tables so why is this not a .get query

        if not results:
            # this ring_obs_id doesn't exist in this table, log this..
            log.error('could not find {0} in table {1} '.format(ring_obs_id,table_name))

        for param,value in results[0].items():
            data.append({param: value})

    if fmt == 'html':
        return render(request, 'detail_metadata_slugs.html',locals())
    if fmt == 'json':
        return HttpResponse(json.dumps(data), content_type="application/json")
    if fmt == 'raw':
        return data, all_info  # includes definitions for opus interface


def get_metadata(request, ring_obs_id, fmt):
    """
    results for a single observation
    all the data, in categories

    pass cols to narrow by particular fields
    pass cat to list value of all fields in named category(s)

    accepts 'cols' as a GET var which is a list of columns by slug
    however the response does not return field names as slugs but as field name
    so this is strange
    TODO:
        make it return cols by slug as field name if cols are slugs (no underscores)
        if cols does has underscores make it return field names as column name
        (this is a fix for backward compatablility )

        and om make 'field' an alias for 'cols' plz omg what is 'cols' even

        if cat is passed returns all in the named category(s) and ignores cols

        you will have to add a column to table_names "slug" to get a
        url-worthy representation of the category name

    """
    update_metrics(request)

    if not ring_obs_id: raise Http404

    try:
        slugs = request.GET.get('cols', False)
        if slugs:
            return get_metadata_by_slugs(request, ring_obs_id, slugs.split(','), fmt)
    except AttributeError:
        pass  # no request was sent

    try:
        cats = request.GET.get('cats',False)
    except AttributeError:
        cats = False  # no request was send, legacy requirement?

    data = SortedDict({})  # will hold data struct to be returned
    all_info = {}  # holds all the param info objects

    # find all the tables (categories) this observation belongs to,
    if not cats:
        all_tables = TableName.objects.filter(display='Y').order_by('disp_order')
    else:
        # restrict table to those found in cats
        all_tables = TableName.objects.filter(table_name__in=cats.split(','), display='Y').order_by('disp_order')

    # now find all params and their values in each of these tables:
    for table in all_tables:
        table_label = table.label
        table_name = table.table_name
        model_name = ''.join(table_name.title().split('_'))

        try:
            table_model = apps.get_model('search', model_name)
        except LookupError:
            log.error("could not find data model for category %s " % model_name)
            continue

        # make a list of all slugs and another of all param_names in this table
        all_slugs = [param.slug for param in ParamInfo.objects.filter(category_name=table_name, display_results=1).order_by('disp_order')]
        all_param_names = [param.name for param in ParamInfo.objects.filter(category_name=table_name, display_results=1).order_by('disp_order')]

        for k, slug in enumerate(all_slugs):
            param_info = get_param_info_by_slug(slug)
            name = param_info.name
            all_info[name] = param_info

        if all_param_names:
            try:
                results = table_model.objects.filter(ring_obs_id=ring_obs_id).values(*all_param_names)[0]

                # results is an ordinary dict so here to make sure we have the correct ordering:
                ordered_results = SortedDict({})
                for param in all_param_names:
                    ordered_results[param] = results[param]

                data[table_label] = ordered_results

            except IndexError:
                # this is pretty normal, it will check every table for a ring obs id
                # a lot of observations do not appear in a lot of tables..
                # for example something on jupiter won't appear in a saturn table..
                # log.error('IndexError: no results found for {0} in table {1}'.format(ring_obs_id, table_name) )
                pass  # no results found in this table, move along
            except AttributeError:
                log.error('AttributeError: no results found for {0} in table {1}'.format(ring_obs_id, table_name) )
                pass  # no results found in this table, move along
            except FieldError:
                log.error('FieldError: no results found for {0} in table {1}'.format(ring_obs_id, table_name) )
                pass  # no results found in this table, move along


    if fmt == 'html':
        # hack becuase we want to display labels instead of param names
        # on our html Detail page
        return render(request, 'detail_metadata.html',locals())
    if fmt == 'json':
        return HttpResponse(json.dumps(data), content_type="application/json")
    if fmt == 'raw':
        return data, all_info  # includes definitions for opus interface


def get_triggered_tables(selections, extras=None):
    """
    this looks at user request and returns triggered tables as list
    always returns the settings.BASE_TABLES
    """
    if not bool(selections):
        return sorted(settings.BASE_TABLES)

    # look for cache:
    cache_no = getUserQueryTable(selections,extras)
    cache_key = 'triggered_tables_' + str(cache_no)
    if (cache.get(cache_key)):
        return sorted(cache.get(cache_key))

    # first add the base tables
    triggered_tables = settings.BASE_TABLES[:]  # makes a copy of settings.BASE_TABLES

    # this is a hack to do something special for the usability of the Surface Geometry section
    # surface geometry is always triggered and showing by default,
    # but for some instruments there is actually no data there.
    # if one of those instruments is constrained directly - that is,
    # one of these instruments is selected in the Instrument Name widget
    # remove the geometry tab from the triggered tables

    # instruments with no surface geo metadata:
    # partables
    fields_to_check = ['obs_general.instrument_id','obs_general.inst_host_id','obs_general.mission_id']
    no_metadata = ['Hubble','CIRS','Galileo']
    for field in fields_to_check:
        if field not in selections:
            continue
        for inst in selections[field]:
            for search_string in no_metadata:
                if search_string in inst:
                    try:
                        triggered_tables.remove('obs_surface_geometry')
                    except Exception as e:
                        log.error(e)
                        log.error(selections)
                        log.error(field)
                        log.error(inst)


    # now see if any more tables are triggered from query
    query_result_table = getUserQueryTable(selections,extras)
    queries = {}  # keep track of queries
    for partable in Partable.objects.all():
        # we are joining the results of a user's query - the single column table of ids
        # with the trigger_tab listed in the partable,
        trigger_tab = partable.trigger_tab
        trigger_col = partable.trigger_col
        trigger_val = partable.trigger_val
        partable = partable.partable


        if partable in triggered_tables:
            continue  # already triggered, no need to check

        # get query
        # did we already do this query?

        if trigger_tab + trigger_col in queries:
            results = queries[trigger_tab + trigger_col]
        else:
            trigger_model = apps.get_model('search', ''.join(trigger_tab.title().split('_')))
            results = trigger_model.objects
            if query_result_table:
                if trigger_tab == 'obs_general':
                    where   = trigger_tab + ".id = " + query_result_table + ".id"
                else:
                    where   = trigger_tab + ".obs_general_id = " + query_result_table + ".id"
                results = results.extra(where=[where], tables=[query_result_table])
            results = results.distinct().values(trigger_col)
            queries.setdefault(trigger_tab + trigger_col, results)

        if (len(results) == 1) and (unicode(results[0][trigger_col]) == trigger_val):
            # we has a triggered table
            triggered_tables.append(partable)

        # surface geometry have multiple targets per observation
        # so we just want to know if our val is in the result (not the only result)
        if 'obs_surface_geometry.target_name' in selections:
            if trigger_tab == 'obs_surface_geometry' and trigger_val == selections['obs_surface_geometry.target_name'][0]:
                if trigger_val in [r['target_name'] for r in results]:
                    triggered_tables.append(partable)


    # now hack in the proper ordering of tables
    final_table_list = []
    for table in TableName.objects.filter(table_name__in=triggered_tables).values('table_name'):
        final_table_list.append(table['table_name'])

    cache.set(cache_key, final_table_list)

    return sorted(final_table_list)


# this should return an image for every row..

@never_cache
def getImages(request,size,fmt):
    update_metrics(request)
    """
    this returns rows from images table that correspond to request
    some rows will not have images, this function doesn't return 'image_not_found' information
    if a row doesn't have an image you get nothing. you lose. good day sir. #fixme #todo

    """
    if not request.session.get('has_session'):
        request.session['has_session'] = True

    session_id = request.session.session_key

    alt_size = request.GET.get('alt_size','')
    columns = request.GET.get('cols',settings.DEFAULT_COLUMNS)

    try:
        [page_no, limit, page, page_ids, order] = getPage(request)
    except TypeError:  # getPage returns False
        raise Http404('could not find page')

    image_links = Image.objects.filter(ring_obs_id__in=page_ids)

    if not image_links:
        log.error('no image found for:')
        log.error(page_ids[:50])

    # page_ids
    if alt_size:
        image_links = image_links.values('ring_obs_id',size,alt_size)
    else:
        image_links = image_links.values('ring_obs_id',size)

    # add the base_path to each image
    all_sizes = ['small','thumb','med','full']
    for k, im in enumerate(image_links):
        for s in all_sizes:
            if s in im:
                image_links[k][s] = get_base_path_previews(im['ring_obs_id']) + im[s]

    # to preserve the order of page_ids as lamely as possible :P
    ordered_image_links = []
    for ring_obs_id in page_ids:
        found = False
        for link in image_links:
            if ring_obs_id == link['ring_obs_id']:
                found = True
                ordered_image_links.append(link)
        if not found:
            # return the thumbnail not found link
            ordered_image_links.append({size:settings.THUMBNAIL_NOT_FOUND, 'ring_obs_id':ring_obs_id})

    image_links = ordered_image_links

    collection_members = get_collection_in_page(page, session_id)

    # find which are in collections, mark unfound images 'not found'
    for image in image_links:
        image['img'] = image[size] if image[size] else 'not found'

        # hack for the new reclassification of some previews as "diagrams"
        image['path'] = settings.IMAGE_HTTP_PATH
        if 'CIRS' in image['ring_obs_id']:
            image['path'] = image['path'].replace('previews','diagrams')

        if collection_members:
            from user_collections.views import *
            if image['ring_obs_id'] in collection_members:
                image['in_collection'] = True

    if (request.is_ajax()):
        template = 'gallery.html'
    else: template = 'image_list.html'

    # image_links
    return responseFormats({'data':[i for i in image_links]},fmt, size=size, alt_size=alt_size, columns_str=columns.split(','), template=template, order=order)


def get_base_path_previews(ring_obs_id):
    # find the proper volume_id to pass to the Files table before asking for file_path
    # (sometimes the Files table has extra entries for an observation with funky paths)
    try:
        volume_id = ObsGeneral.objects.filter(ring_obs_id=ring_obs_id)[0].volume_id
    except IndexError:
        return

    file_path = Files.objects.filter(ring_obs_id=ring_obs_id, volume_id=volume_id)[0].base_path

    base_path = '/'.join(file_path.split('/')[-2:])

    return base_path


def getImage(request,size='med', ring_obs_id='',fmt='mouse'):      # mouse?
    """
    size = thumb, small, med, full
    return ring_obs_id + ' ' + size

    return HttpResponse(img + "<br>" + ring_obs_id + ' ' + size +' '+ fmt)
    """
    update_metrics(request)
    try:
        img = Image.objects.filter(ring_obs_id=ring_obs_id).values(size)[0][size]
    except IndexError:
        log.error('index error could not find ring_obs_id {}'.format(ring_obs_id))
        return

    path = settings.IMAGE_HTTP_PATH + get_base_path_previews(ring_obs_id)
    if 'CIRS' in ring_obs_id:
        path = path.replace('previews','diagrams')

    return responseFormats({'data':[{'img':img, 'path':path}]}, fmt, size=size, path=path, template='image_list.html')

def file_name_cleanup(base_file):
    base_file = base_file.replace('.','/')
    base_file = base_file.replace(':','/')
    base_file = base_file.replace('[','/')
    base_file = base_file.replace(']','/')
    base_file = base_file.replace('.','/')
    base_file = base_file.replace('//','/')
    base_file = base_file.replace('///','/')
    return base_file


# loc_type = path or url
# you broke this see http://127.0.0.1:8000/opus/api/files.json?&target=pan
def getFilesAPI(request, ring_obs_id=None, fmt=None, loc_type=None):

    if not ring_obs_id:
        ring_obs_id = ''
    if not fmt:
        fmt = 'raw'  # the format this function returns
    if not loc_type:
        loc_type = 'url'

    update_metrics(request)

    product_types = request.GET.get('types',[])
    previews = request.GET.get('previews',[])

    if product_types:
        product_types = product_types.split(',')
    if previews:
        previews = previews.split(',')

    # we want the api to return all possible files unless otherwise described
    if not product_types:
        product_types = 'all'

    if not previews:
        previews = 'all'
    if previews == ['none']:
        previews = []

    if request and request.GET and not ring_obs_id:

        # no ring_obs_id passed, get files from search results
        (selections,extras) = urlToSearchParams(request.GET)
        page  = getData(request,'raw')['page']
        if not len(page):
            return False
        ring_obs_id = [p[0] for p in page]

    return getFiles(ring_obs_id=ring_obs_id, fmt=fmt, loc_type=loc_type, product_types=product_types, previews=previews)


# loc_type = path or url
def getFiles(ring_obs_id=None, fmt=None, loc_type=None, product_types=None, previews=None, collection=None, session_id=None):
    """
    returns list of all files by ring_obs_id
    ring_obs_id can be string or list
    can also return preview files too
    """
    if collection and not session_id:
        log.error("needs session_id in kwargs to access collection")
        return False

    # handle passed params
    if not fmt:
        fmt = 'raw'
    if not loc_type:
        loc_type = 'url'
    if not product_types:
        product_types = ['all']  # if types or previews aren't filtered then return them alls
    if not previews:
        previews = ['all']
    if not collection:
        collection = False

    # apparently you can also pass in a string if you are so inclined *sigh*
    if type(product_types).__name__ != 'list':
        product_types = product_types.split(',')
    if type(previews).__name__ != 'list':
        previews = previews.split(',')

    if previews == ['all']:
        previews = [i[0] for i in settings.image_sizes]
    if previews == ['none'] or previews == 'none':
        previews = []

    # this is either for a collection or some ring_obs_id:
    if ring_obs_id:
        # ring_obs_id may be passed in as a string or a list,
        # if it's a string make it a list
        if type(ring_obs_id) is unicode or type(ring_obs_id).__name__ == 'str':
            ring_obs_ids = [ring_obs_id]
        else:
            ring_obs_ids = ring_obs_id

    elif collection:
        # no ring_obs_id, this must be for a colletion
        colls_table_name = get_collection_table(session_id)

        where   = "files.ring_obs_id = " + connection.ops.quote_name(colls_table_name) + ".ring_obs_id"
    else:
        log.error('no ring_obs_ids or collection specified in results.getFiles')
        return False

    # you can ask this function for url paths or disk paths
    if loc_type == 'url':
        path = settings.FILE_HTTP_PATH
    else:
        path = settings.FILE_PATH

    # start building up the query of the Files model
    files_table_rows = Files.objects

    if collection:
        files_table_rows = files_table_rows.extra(where=[where], tables=[colls_table_name])
    else:
        files_table_rows = files_table_rows.filter(ring_obs_id__in=ring_obs_ids)

    if product_types != ['all'] and product_types != ['none']:
        files_table_rows = files_table_rows.filter(product_type__in=product_types)

    if not files_table_rows:
        log.error('no rows returned in file table')

    file_names = {}
    for f in files_table_rows:
        """
        This loop is looping over the entire result set to do a text transoformation (into json)
        todo: STOP THE MADNESS
        move most of this to database layer
        put all of the below into the file sizes table
        then just grab direct from file sizes table by product_type and ring_obs_id
        """

        # file_names are grouped first by ring_obs_id then by product_type
        ring_obs_id = f.ring_obs_id
        file_names.setdefault(ring_obs_id, {})

        # add some preview images?
        if len(previews):
            file_names[ring_obs_id]['preview_image'] = []
            for size in previews:
                url_info = getImage(False, size.lower(), ring_obs_id,'raw')
                if not url_info:
                    continue  # no image found for this observation so let's skip it
                url = url_info['data'][0]['img']
                base_path = url_info['data'][0]['path']
                if url:
                    if loc_type == 'path':
                        url = settings.IMAGE_PATH + get_base_path_previews(ring_obs_id) + url
                    else:
                        url = base_path + url

                    file_names[ring_obs_id]['preview_image'].append(url)

        if product_types == ['none']:
            continue

        # get PDS products
        # get this file's volume location
        file_extensions = []
        try:
            volume_loc = ObsGeneral.objects.filter(ring_obs_id=ring_obs_id)[0].volume_id
        except IndexError:
            volume_loc = f.volume_id

        # file_names are grouped first by ring_obs_id then by product_type
        file_names[ring_obs_id].setdefault(f.product_type, [])
        extra_files = []
        if f.extra_files:
            extra_files = f.extra_files.split(',')

        ext = ''.join(f.file_specification_name.split('.')[-1:])
        base_file = '.'.join(f.file_specification_name.split('.')[:-1])

        # // sometimes in GO the volume_id is appended already
        if base_file.find(f.volume_id + ":")>-1:
            base_file = ''.join(base_file.split(':')[1:len(base_file.split(':'))])

        # // strange punctuation in the base file name is really a directory division
        base_file = file_name_cleanup(base_file).strip('/')

        if f.label_type.upper() == 'DETACHED':
            if f.product_type not in ['TIFF_PREVIEW_IMAGE','JPEG_PREVIEW_IMAGE']:  # HST hack
                file_extensions += ['LBL']

        if f.ascii_ext: file_extensions += [f.ascii_ext]
        if f.lsb_ext: file_extensions += [f.lsb_ext]
        if f.msb_ext: file_extensions += [f.msb_ext]
        if f.detached_label_ext: file_extensions += [f.detached_label_ext]

        file_extensions = list(set(file_extensions))

        # now adjust the path whether this is on the derived directory or not
        if (f.product_type) == 'CALIBRATED':
            if loc_type != 'url':
                path = settings.DERIVED_PATH
            else:
                path = settings.DERIVED_HTTP_PATH
        else:
            if loc_type == 'path':
                path = settings.FILE_PATH
            else:
                path = settings.FILE_HTTP_PATH

        path = path + f.base_path.split('/')[-2] + '/'  # base path like xxx

        # add the extra_files
        for extra in extra_files:
            file_names[ring_obs_id][f.product_type] += [path + volume_loc + '/' + extra]

        for extension in file_extensions:
            file_names[ring_obs_id][f.product_type]  += [path + volume_loc + '/' + base_file + '.' + extension]
        # // add the original file
        file_names[ring_obs_id][f.product_type]  += [path + volume_loc + '/' + base_file + '.' + ext]
        file_names[ring_obs_id][f.product_type] = list(set(file_names[ring_obs_id][f.product_type])) #  makes unique
        file_names[ring_obs_id][f.product_type].sort()
        file_names[ring_obs_id][f.product_type].reverse()


    if fmt == 'raw':
        return file_names

    if fmt == 'json':
        return HttpResponse(json.dumps({'data':file_names}), content_type='application/json')

    if fmt == 'html':
        raise Http404
        data = file_names
        return render("list.html", data)


def getPage(request, colls=None, colls_page=None, page=None):
    update_metrics(request)
    """
    the gets the metadata and images to build a page of results
    """
    # get some stuff from the url or fall back to defaults
    if not request.session.get('has_session'):
        request.session['has_session'] = True

    session_id = request.session.session_key

    if not colls:
        collection_page = request.GET.get('colls',False)
    else:
        collection_page = colls

    limit = request.GET.get('limit',100)
    limit = int(limit)
    slugs = request.GET.get('cols', settings.DEFAULT_COLUMNS)
    if not bool(slugs):
        slugs = settings.DEFAULT_COLUMNS  # i dunno why the above doesn't suffice

    columns = []
    for slug in slugs.split(','):
        try:
            columns += [ParamInfo.objects.get(slug=slug).param_name()]
        except ParamInfo.DoesNotExist:
            if '1' in slug:
                # single column range slugs will not have the index, but
                # will come in with it because of how ui is designed, so
                # look for the slug without the index
                temp_slug = slug[:-1]
                try:
                    columns += [ParamInfo.objects.get(slug=temp_slug).param_name()]
                except ParamInfo.DoesNotExist:
                    continue

    triggered_tables = list(set([param_name.split('.')[0] for param_name in columns]))
    try:
        triggered_tables.remove('obs_general')  # we remove it because it is the primary
                                                # model so don't need to add it to extra tables
    except ValueError:
        pass  # obs_general isn't in there

    if not collection_page:
        # this is for a search query

        order = request.GET.get('order','time1')

        # figure out column order in table
        if order:
            try:
                descending = '-' if order[0] == '-' else None
                order_slug = order.strip('-')  # strip off any minus sign to look up param name
                order = ParamInfo.objects.get(slug=order_slug).param_name()
                if descending:
                    order = '-' + order
            except DoesNotExist:
                order = False

        # figure out page we are asking for
        if not page:
            page_no = request.GET.get('page',1)
            if page_no != 'all':
                page_no = int(page_no)
        else:
            page_no == page

        # ok now that we have everything from the url get stuff from db
        (selections,extras) = urlToSearchParams(request.GET)
        user_query_table = getUserQueryTable(selections,extras)

        # figure out what tables do we need to join in and build query
        triggered_tables.append(user_query_table)
        where   = "obs_general.id = " + connection.ops.quote_name(user_query_table) + ".id"
        results = ObsGeneral.objects.extra(where=[where], tables=triggered_tables)

    else:
        # this is for a collection

        # find the ordering
        order = request.GET.get('colls_order', False)
        if not order:
            # get regular order if collections doesn't have a special order
            order = request.GET.get('order',False)

        if order:
            try:
                order_param = order.strip('-')  # strip off any minus sign to look up param name
                descending = order[0] if (order[0] == '-') else None
                order = ParamInfo.objects.get(slug=order_param).name
                if descending:
                    order = '-' + order
            except DoesNotExist:
                order = False

        if not colls_page:
            page_no = request.GET.get('colls_page',1)
            if page_no != 'all':
                page_no = int(page_no)
        else:
            page_no = colls_page

        # figure out what tables do we need to join in and build query
        triggered_tables = list(set([t.split('.')[0] for t in columns]))
        try:
            triggered_tables.remove('obs_general')
        except ValueError:
            pass  # obs_general table wasn't in there for whatever reason

        # join in the collections table
        colls_table_name = get_collection_table(session_id)
        triggered_tables.append(colls_table_name)
        where   = "obs_general.ring_obs_id = " + connection.ops.quote_name(colls_table_name) + ".ring_obs_id"
        results = ObsGeneral.objects.extra(where=[where], tables=triggered_tables)

    # now we have results object (either search or collections)
    if order:
        results = results.order_by(order)

    # this is the thing you pass to django model via values()
    # so we have the table names a bit to get what django wants:
    column_values = []
    for param_name in columns:
        table_name = param_name.split('.')[0]
        if table_name == 'obs_general':
            column_values.append(param_name.split('.')[1])
        else:
            column_values.append(param_name.split('.')[0].lower().replace('_','') + '__' + param_name.split('.')[1])

    """
    the limit is pretty much always 100, the user cannot change it in the interface
    but as an aide to finding the right chunk of a result set to search for
    for the 'add range' click functinality, the front end may send a large limit, like say
    page_no = 42 and limit = 400
    that means start the page at 42 and go 4 pages, and somewhere in there is our range
    this is how 'add range' works accross multiple pages
    so the way of computing starting offset here should always use the base_limit of 100
    using the passed limit will result inthe wront offset because of way offset is computed here
    this may be an aweful hack.
    """
    # todo: redux: look at line 559 you are essentially doing this query twice? in the same method and peforming the query each time cuz it has changed!
    if page_no != 'all':
        base_limit = 100  # explainer of sorts is above
        offset = (page_no-1)*base_limit # we don't use Django's pagination because of that count(*) that it does.
        results = results.values_list(*column_values)[offset:offset+int(limit)]
    else:
        results = results.values_list(*column_values)

    # return a simple list of ring_obs_ids
    ring_obs_id_index = column_values.index('ring_obs_id')
    page_ids = [o[ring_obs_id_index] for o in results]

    if not len(page_ids):
        return False

    return [page_no, limit, list(results), page_ids, order]
