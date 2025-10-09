#!/usr/bin/python3
import requests
import xml.etree.ElementTree as ET
import sys
import logging
import os
import getpass
import time

'''
THIS SCRIPT REQUIRES:
1. Old item ID

For each item ID:
Check for external ID
-if found, pass
-if not found:
--get item's URI value
--pull the name of the folder immediately following "/ateme_transcodes/" (this is the external ID)
--conduct a search for items containing the folder name as its external ID
--delete the item found
--stamp the external ID to the item we started with

URI example:
file:///mnt/Mezz/mam/prod/import/transcodes/ateme_transcodes/VX-2098946-CL_HD_MP2_15000_DD20_none_CC_eng/VX-2098945/In_Demand_GOLDEN_COMPASS_THE_HD_16x9_E0399670_FEATURE_STEREO_6466680_CONFORMED_CL_HD_MP2_15000_DD20_none_CC.mpg
'''

def get_env():
	# this function asks the user to enter the environment name
	print()
	env = input('Enter the environment we are restarting failed proxies on: (dev, uat, prod)\n')
	env = env.lower()
	if env == 'dev' or env == 'uat' or env == 'prod':
		print(f'\nThank you kind sir/madam for your most generous and enlightening instructions. We will be working on: {env}.\n')
		return env
	else:
		print('\noops try again. must be dev, uat, or prod\n')
		get_env()
		
# check if an environment arguement was passed to the script, if not ask for input

if len(sys.argv) == 1:
	# sys.argv[0] is always the script's path so that would count as the one argument
	# so we know the argument was not passed - ask for user input
	environment = get_env()
else:
	# more than one argument was passed so lets see if the format is good
	environment = sys.argv[1]
	environment = environment.lower()
	if environment not in ["prod","dev","uat"]:
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

def external_id_check(vs,vs_auth,item_id):
	get_url = f'{vs}API/item/{item_id}/metadata;field=__external_id'
	headers = {
		'Accept': 'application/xml',
		'Authorization': vs_auth
	}
	get_response = xml_prep(requests.get(get_url, headers=headers))
	if get_response.find('item/metadata/timespan/field/value') is None:
		print(f'No external ID found in item {item_id}!')
		return item_id
	else:
		print(f'External ID found in item {item_id}.\n\n\n')
		return False

def get_external_from_uri(vs,vs_auth,item_id):
	uri_url = f'{vs}API/item/{item_id}/metadata;field=originalUri'
	headers = {
		'Accept': 'application/xml',
		'Authorization': vs_auth
	}
	uri_response = xml_prep(requests.get(uri_url, headers=headers))
	original_uri = uri_response.find('item/metadata/timespan/field/value').text
	uri_external_id = original_uri.replace('file:///mnt/Mezz/mam/prod/import/transcodes/ateme_transcodes/','').split('/')[0]
	return uri_external_id

def search_for_external_id(vs,vs_auth,external_id):
	search_url = f'{vs}API/item'
	headers = {
		'Accept': 'application/xml',
		'Content-type': 'application/xml',
		'Authorization': vs_auth
	}
	body = f'''
    <ItemSearchDocument version="2"  xmlns="http://xml.vidispine.com/schema/vidispine">
        <intervals>generic</intervals>
        <field>
            <name>__external_id</name>
            <value>{external_id}</value>
        </field>
    </ItemSearchDocument>
    '''
	response = xml_prep(requests.put(search_url, headers=headers, data=body))
	if response.find('hits').text != '1':
		hits = response.find('hits').text
		print(f'Found {hits} items with external ID {external_id}. We were expecting 1. CHECK YOUR SHIT.')
		exit(1)
	else:
		return response.find('item').attrib['id']

def delete_bad_item(vs,vs_auth,item_id_with_external):
	del_url = f'{vs}API/item/{item_id_with_external}'
	headers = {
		'Accept': 'application/xml',
		'Authorization': vs_auth
	}
	del_response = requests.delete(del_url, headers=headers)	
	if del_response.status_code != 200:
		print(f'Failed to delete {item_id_with_external}! Aborting.')
		exit(1)
	else:
		print(f'Successfully deleted {item_id_with_external}.')
		time.sleep(10)
		return True

def stamp_external_id(vs,vs_auth,uri_external_id,item_without_id):
	put_url = f'{vs}API/item/{item_without_id}/metadata'
	headers = {
		'Accept': 'application/xml',
		'Authorization': vs_auth
	}
	body = f'''
    <MetadataDocument xmlns="http://xml.vidispine.com/schema/vidispine">
        <timespan end="+INF" start="-INF">
            <field>
                <name>__external_id</name>
                <value>{uri_external_id}</value>
            </field>        
        </timespan>
    </MetadataDocument>
    '''
	put_response = requests.put(put_url, headers=headers, data=body)
	if put_response.status_code != 200:
		print(f'Failed to put external ID {uri_external_id} into item {item_without_id}! Aborting.')
		exit(1)
	else:
		print(f'Successfully put external ID {uri_external_id} into item {item_without_id}.\n\n\n')
		time.sleep(10)
		return True

def main(environment,proxy_config_file,script_file_name):
	user = getpass.getuser()
	logging.info(f'{environment}: COMMENCING: {script_file_name} executed by {user}')
	proxy_config = ET.parse(proxy_config_file)
	vs,vs_auth = get_variables_from_config(environment,proxy_config)
	item_list = open('itemIds.txt', 'r')
	for item in item_list:
		item = item.strip()
		item_without_id = external_id_check(vs,vs_auth,item)
		if item_without_id:
			uri_external_id = get_external_from_uri(vs,vs_auth,item_without_id)
			print(f'{item_without_id} External ID from URI: {uri_external_id}')
			item_id_with_external = search_for_external_id(vs,vs_auth,uri_external_id)
			print(f'External ID {uri_external_id} found in item {item_id_with_external}.')
			delete_bad_item(vs,vs_auth,item_id_with_external)
			stamp_external_id(vs,vs_auth,uri_external_id,item_without_id)
	return True

main(environment,proxy_config_file,script_file_name)
exit(0)