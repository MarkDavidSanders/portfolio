#!/usr/bin/python3
'''
This Starter Pack list has a column of checksums that don't have item IDs.
I think this is because they are corrupt or missing.
So.

-Get checksum from list
-Search checksum for item
-Check item's metadata for indab_master_id value
-If no master ID, feature cannot be found
-If master ID, search VS for items with that master ID
-Check metadata of each returned item for file_information_subtype_descriptor
-Check metadata of each returned item for file_information_is_trailer
-Compile list of qualified features/trailers
    -For features, file_information_subtype_descriptor value MUST be "CL_HD_MP2_15000"
    -For trailers, subtype SHOULD be HD but doesn't have to be
-If list is empty, feature/trailer cannot be found
-Otherwise, check items to make sure they're in house and not corrupt
-If multiple items pass checks, return item with highest ID
-If nothing passes checks, feature/trailer cannot be found
'''

import xml.etree.ElementTree as ET
import sys
import logging
import os
import getpass
import requests

def get_env():
    '''this function asks the user to enter the environment name'''
    env = input('Enter the environment we are restarting failed proxies on: (dev, uat, prod)\n')
    env = env.lower()
    if env not in ['dev', 'uat', 'prod']:
        print('\noops try again. must be dev, uat, or prod\n')
        get_env()
    print(f'\nWe will be working on: {env}.\n')
    return env

# check if an environment argument was passed to the script, if not ask for input
if len(sys.argv) == 1:
    # sys.argv[0] is always the script's path so that would count as the one argument
    # so we know the argument was not passed - ask for user input
    environment = get_env()
else:
    # more than one argument was passed so lets see if the format is good
    environment = sys.argv[1]
    environment = environment.lower()
    if environment not in ("prod","dev","uat"):
        # format of the enviroment argument wasn't good, ask for user input
        print()
        print('Argument passed to script was not an environment name: dev, uat, or prod')
        print(f'Argument passed: {sys.argv[1]}')
        print()
        environment = get_env()

script_path = sys.argv[0]
# get the script file name from the path
script_file_name = script_path[script_path.rfind('/')+1:]
script_file_name_no_extention = script_file_name[0:script_file_name.rfind('.')]
log_file = script_path.replace(script_file_name,script_file_name_no_extention+'.log')
proxy_config_file = script_path.replace(script_file_name,'proxy_config.xml')

if not os.path.exists(log_file):
    # use with to create the file via open() and it will close automatically
    with open(log_file, 'w', encoding='utf-8'):
        pass

logging.basicConfig(filename=log_file,
                    level=logging.DEBUG,
                    format='%(asctime)s %(levelname)s: %(message)s')

# functions
def xml_prep(res):
    '''prepare a VS xml for parsing with ET'''
    res = res.content
    res = res.decode(encoding='utf-8', errors='strict')
    # because I hate dealing with the namespace in ET
    res = res.replace(' xmlns=\"http://xml.vidispine.com/schema/vidispine\"', "")
    res = res.encode(encoding='utf-8', errors='strict')
    res = ET.fromstring(res)
    return res

def get_variables_from_config(env_name, proxy_config):
    '''get variables from config file'''
    env = proxy_config.findall('environment')
    for e in env:
        if e.find('short_name').text == env_name:
            vs = e.find('vidispine/ip_address').text
            vs_auth = e.find('vidispine/auth').text
            break
    return vs,vs_auth

def build_search_doc(group,field,value):
    '''build the search doc, ya dummy'''
    data = f'''
    <ItemSearchDocument xmlns="http://xml.vidispine.com/schema/vidispine">
        <intervals>generic</intervals>
            <group>
                <name>{group}</name>
                <field>
                    <name>{field}</name>
                    <value>{value}</value>
                </field>
            </group>
    </ItemSearchDocument>
    '''
    return data

def get_item_from_checksum(vs,vs_auth,checksum):
    '''get item ID from checksum'''
    data = build_search_doc(
        'original_shape_mi','original_shape_mi_original_shape_mi_md5_hash',checksum)
    item_id = item_search(vs,vs_auth,data)
    if item_id:
        return item_id[0]
    return False

def item_search(vs,vs_auth,data):
    '''search VS for items with metadata values matching the search doc'''
    url = vs+'API/item'
    headers = {
        'Accept': 'application/xml',
        'Content-type': 'application/xml',
        'Authorization': vs_auth
    }
    response = requests.put(url, headers=headers, data=data)
    item_list_doc = xml_prep(response)
    hits = int(item_list_doc.find('hits').text)
    number = 1000
    first = 1
    item_list = []
    while hits >= first:
        url = f'{vs}API/item;first={str(first)};number={str(number)}'
        response = requests.put(url, headers=headers, data=data)
        items = xml_prep(response)
        for item in items.findall('item'):
            item_id = item.attrib['id']
            item_list.append(item_id)
        first += number
    if not item_list:
        return False
    return item_list

def get_system_metadata_value(vs,vs_auth,item_id,field):
    '''get metadata value for system-level fields'''
    url = f'{vs}API/item/{item_id}/metadata;field={field}'
    headers = {
        'Accept': 'application/xml',
        'Authorization': vs_auth
    }
    response = xml_prep(requests.get(url, headers=headers))
    try:
        metadata_value = response.find('item/metadata/timespan/field/value').text
        return metadata_value
    except AttributeError:
        # doesn't have the field
        return False

def get_group_metadata_value(vs,vs_auth,item_id,field):
    '''get metadata value for grouped fields'''
    url = f'{vs}API/item/{item_id}/metadata;field={field}'
    headers = {
        'Accept': 'application/xml',
        'Authorization': vs_auth
    }
    response = xml_prep(requests.get(url, headers=headers))
    try:
        groups = response.findall('item/metadata/timespan/group')
        metadata_value = ''
        for group in groups:
            if group.find('field/name').text == field:
                metadata_value = group.find('field/value').text
                break
        if metadata_value in ('', None):
            return False
        return metadata_value
    except AttributeError:
        # doesn't have the field
        return False

def get_shape_file(vs, vs_auth, item_id):
    '''pull up an item's shape'''
    url = f'{vs}API/item/{item_id}?content=shape&tag=original'
    headers = {
        'Accept': 'application/xml',
        'Authorization': vs_auth
    }
    response = xml_prep(requests.get(url, headers=headers))
    shape_file = response.find('shape/containerComponent/file')
    return shape_file

def compile_feature_candidate_list(vs,vs_auth,indab_items):
    '''parse list of items to find HD 15.0 features'''
    candidate_list = []
    for item in indab_items:
        # subtype/trailer check
        subtype = get_group_metadata_value(vs,vs_auth,item,'file_information_subtype_descriptor')
        is_trailer = get_group_metadata_value(vs,vs_auth,item,'file_information_is_trailer')
        if subtype and "CL_HD_MP2_15000" in subtype and is_trailer in ('false', 'False', False):
            # in house/corrupt check
            corrupt = get_group_metadata_value(vs,vs_auth,item,'media_management_corrupt')
            shape_presence = get_shape_file(vs, vs_auth, item)
            if (corrupt and corrupt.lower() == 'true') or shape_presence is None:
                continue
            print(f'Item {item} is a qualified CL_HD_MP2_15000 derivative.')
            candidate_list.append(item)
    return candidate_list

def compile_trailer_candidate_list(vs,vs_auth,indab_items):
    '''parse list of items to find HD 15.0 trailers, or SD if no HD trailers exist'''
    trailer_candidates = []
    for item in indab_items:
        # subtype/trailer check
        is_trailer = get_group_metadata_value(vs,vs_auth,item,'file_information_is_trailer')
        subtype = get_group_metadata_value(vs,vs_auth,item,'file_information_subtype_descriptor')
        if subtype and "CL_HD_MP2_15000" in subtype and is_trailer.lower() == 'true':
            # in house/corrupt check
            corrupt = get_group_metadata_value(vs,vs_auth,item,'media_management_corrupt')
            shape_presence = get_shape_file(vs, vs_auth, item)
            if (corrupt and corrupt.lower() == 'true') or shape_presence is None:
                continue
            print(f'Trailer {item} is a qualified HD derivative.')
            trailer_candidates.append(item)
    if len(trailer_candidates) == 0:
        print('No HD trailers found; looking for SD trailers.')
        for item in indab_items:
            # subtype/trailer check
            is_trailer = get_group_metadata_value(vs,vs_auth,item,'file_information_is_trailer')
            subtype = get_group_metadata_value(vs,vs_auth,item,
                                               'file_information_subtype_descriptor')
            if subtype and subtype == "CL_SD_MP2_03750_DD20" and is_trailer.lower() == 'true':
                # in house/corrupt check
                corrupt = get_group_metadata_value(vs,vs_auth,item,'media_management_corrupt')
                shape_presence = get_shape_file(vs, vs_auth, item)
                if (corrupt and corrupt.lower() == 'true') or shape_presence is None:
                    continue
                print(f'Trailer {item} is a qualified SD derivative.')
                trailer_candidates.append(item)
    return trailer_candidates

def main():
    '''here we go'''
    user = getpass.getuser()
    logging.info('%s: COMMENCING: %s executed by %s', environment, script_file_name, user)
    proxy_config = ET.parse(proxy_config_file)
    vs,vs_auth = get_variables_from_config(environment, proxy_config)
    resultsfile = open('checksum_replacement_check2.csv', 'w+', encoding='utf-8')
    resultsfile.write('Old MD5,Feature ID,Feature MD5,Filename,Trailer ID,Trailer MD5,Filename\r')

    with open('checksum_list.txt', 'r', encoding='utf-8') as f:
        checksum_list = f.readlines()

    for checksum in checksum_list:
        checksum = checksum.strip()
        print(f'Old Checksum: {checksum}')

        # get item ID from checksum
        # N/A if not found
        item_id = get_item_from_checksum(vs,vs_auth,checksum)
        if not item_id:
            print(f'No item found with checksum {checksum}.\n')
            resultsfile.write((f'{checksum},N/A,N/A,N/A,N/A,N/A,N/A\r'))
            continue

        # get Indab master ID from item ID
        indab_master_id = get_group_metadata_value(vs,vs_auth,item_id,'indab_master_id')
        if not indab_master_id or indab_master_id == '0':
            print('No Indab master ID found.\n')
        else:
            print(f'Indab master ID: {indab_master_id}')

            # search for all items with Indab master ID
            data = build_search_doc('indab','indab_master_id',indab_master_id)
            indab_items = item_search(vs,vs_auth,data)
            # no need to check indab_items for empty list; it'll always have at least one ID in it

        # if no Indab master ID, use the item ID we just found
        if not indab_master_id or indab_master_id == '0':
            feature_candidates = [item_id]

        # otherwise, find HD feature from search
        else:
            feature_candidates = compile_feature_candidate_list(vs,vs_auth,indab_items)
            if len(feature_candidates) == 0:
                print(f'No HD features found for Indab master ID {indab_master_id}.\n')
                # Put 'N/A' in list to avoid errors later
                feature_candidates = ['N/A']
            print(f'Feature ID: {max(feature_candidates)}.')

        # get feature checksum (and filename just to be sure)
        if max(feature_candidates) != 'N/A':
            feature_md5 = get_group_metadata_value(vs,vs_auth,max(feature_candidates),
                                                   'original_shape_mi_original_shape_mi_md5_hash')
            feature_filename = get_system_metadata_value(vs,vs_auth,max(feature_candidates),
                                                        'originalFilename')
            print(f'{feature_filename}\n{feature_md5}\n')

        # find HD or SD trailer from search
        trailer_candidates = compile_trailer_candidate_list(vs,vs_auth,indab_items)
        if len(trailer_candidates) == 0:
            print(f'No trailers found for Indab master ID {indab_master_id}.\n')
            # Put 'N/A' in list to avoid errors later
            trailer_candidates = ['N/A']
        print(f'Trailer ID: {max(trailer_candidates)}.')

        # get trailer checksum / filename
        if max(trailer_candidates) != 'N/A':
            trailer_md5 = get_group_metadata_value(vs,vs_auth,max(trailer_candidates),
                                                   'original_shape_mi_original_shape_mi_md5_hash')
            trailer_filename = get_system_metadata_value(vs,vs_auth,max(trailer_candidates),
                                                        'originalFilename')
            print(f'{trailer_filename}\n{trailer_md5}\n')

        # write results to file
        resultsfile.write((f'{checksum},'
                           f'{max(feature_candidates)},{feature_md5},{feature_filename},'
                           f'{max(trailer_candidates)},{trailer_md5},{trailer_filename}\r'))

    print('Done.')

main()
exit(0)
