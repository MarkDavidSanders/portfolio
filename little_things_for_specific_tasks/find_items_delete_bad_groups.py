#!/usr/bin/python3
# script version and log level
script_version = "241226.14"
log_level = "INFO" # DEBUG INFO WARN ERROR

'''
THIS SCRIPT WILL: 
-Get URL info and all that stuff from Vault
-Search Vidispine for search_doc contents
-Compile results into list of item IDs
-Compile list of bad changesets:
    -Get metadata changes of each listed item
        -Search each changeset for "deriv" anywhere in any group name and log the set ID if there's a hit
-Send a delete call for every set in the list

IT NEEDS:
-Environment (passed as argument)
-Search_doc contents (defined below, edited by user as needed)
'''

search_doc = '''
<ItemSearchDocument xmlns="http://xml.vidispine.com/schema/vidispine">
    <intervals>generic</intervals>
    <field>
        <name>file_information_subtype</name>
        <value>*Derivative*</value>
    </field>
    <group>
        <name>mezz_wf_orig</name>
        <field>
            <name>mezz_wf_orig_status</name>
            <value>*</value>
        </field>
    </group>
    <field>
        <name>__placeholder_shape_size</name>
        <value>1</value>
    </field>
</ItemSearchDocument>
'''

# imports
import getpass
import logging
import os
import sys # argv
import requests
import xml.etree.ElementTree as ET

# args to variables
if len(sys.argv) == 2:
    env = sys.argv[1].lower()
else:
    env = input('Enter the environment we are working in: ').lower()

# set up other global variables:

script_path = sys.argv[0]
# get the script file name from the path
script_file_name = script_path[script_path.rfind('/')+1:]
script_file_name_no_extention = script_file_name[0:script_file_name.rfind('.')]
log_file = script_path.replace(script_file_name,script_file_name_no_extention+'.log')
proxy_config_file = script_path.replace(script_file_name,'proxy_config.xml')
if not os.path.exists(log_file):
	# use with to create the file via open() and it will close automatically
	with open(log_file, 'w'): pass

logging.basicConfig(filename=log_file, level=logging.DEBUG, format='%(asctime)s %(levelname)s: %(message)s')

# functions
def xml_prep(res):
	# prepare a VS xml for parsing with ET
	res = res.content
	res = res.decode(encoding='utf-8', errors='strict')
	# because I hate dealing with the namespace in ET
	res = res.replace(' xmlns=\"http://xml.vidispine.com/schema/vidispine\"', "")
	res = res.encode(encoding='utf-8', errors='strict')
	res = ET.fromstring(res)
	return res

def get_variables_from_config(environment,proxy_config):
	env = proxy_config.findall('environment')
	for e in env:
		if e.find('short_name').text == environment:
			vs = e.find('vidispine/ip_address').text
			vs_auth = e.find('vidispine/auth').text
			break
	return vs,vs_auth

def get_items(vs,vs_auth,search_doc) -> list:
	# use an auto refresh token if this is a long list being composed
	url = f'{vs}API/item'
	headers = {
		'Accept': 'application/xml',
		'Content-type': 'application/xml',
		'Authorization': vs_auth
	}
	data = search_doc
	response = requests.put(url, headers=headers, data=data)
	item_list_doc = xml_prep(response)
	hits = int(item_list_doc.find('hits').text)
	print(f'There are {str(hits)} hits returned in this search.')
	print('Compiling list of items.')
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
	return item_list

def find_bad_changes(vs,vs_auth,item):
    url = f'{vs}API/item/{item}/metadata/changes'
    headers = {
        'Accept': 'application/xml',
        'Authorization': vs_auth
    }
    response = requests.get(url, headers=headers)
    changes_doc = xml_prep(response)
    changes = changes_doc.findall('changeSet')
    subtype = ''
    for change in changes:
        if subtype:
            break
        groups = change.findall('metadata/timespan/group/name')
        for group in groups:
             do stuff
    bad_sets = []
    for change in changes:
        change_id = change.find('id').text
        groups = change.findall('metadata/timespan/group/name')
        group_names = []
        for group in groups:
             group_names.append(group.text)
        for group_name in group_names:
             if not group_name.startswith(subtype):
                  bad_sets.append(change_id)
                  break
    if len(bad_sets) > 0:
        return bad_sets
    else:
        print(f'{item} has no bad fields. Why did you submit it?')
        return 0

def delete_changes(vs,vs_auth,bad_changes):
    # bad_changes is a dictionary with item IDs as keys and an array of change IDs as values
    headers = {
        'Accept': 'application/xml',
        'Authorization': vs_auth
    }
    for key in bad_changes:
        if bad_changes[key] != 0:
            for x in range(len(bad_changes[key])):
                change_id = bad_changes[key][x]
                del_url = f'{vs}API/item/{key}/metadata/changes/{change_id}'
                response = requests.delete(del_url, headers=headers)
                if response.status_code != 200:
                    logging.error(f'Change ID {change_id} delete for item {key}: status code {response.status_code}')
                    exit(1)
                logging.info(f'Change ID {change_id} delete for item {key}: status code {response.status_code}')
            print(f'Item {key} has been SCRUBBED of conflicting metadata. Yeah!')
    return True

def find_and_delete(search_doc):
    user = getpass.getuser()
    logging.info(f'{env}: COMMENCING: {script_file_name} executed by {user}')
    proxy_config = ET.parse(proxy_config_file)
    vs,vs_auth = get_variables_from_config(env,proxy_config)
    item_list = get_items(vs,vs_auth,search_doc)
    bad_changes = {}
    for item in item_list:
        bad_changes[item] = find_bad_changes(vs,vs_auth,item)
    x = delete_changes(vs,vs_auth,bad_changes)
    if not x:
        return False
    return True


if __name__ == "__main__":
    s = find_and_delete(search_doc)
    if s:
        exit(0)
    else:
        print("BAD ENDING.")
        exit(1)