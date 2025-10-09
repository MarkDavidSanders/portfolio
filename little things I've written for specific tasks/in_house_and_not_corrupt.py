#!/usr/bin/python3
import requests
import xml.etree.ElementTree as ET
import sys
import logging
import os
import getpass

'''
Get item ID from list
Check metadata for media_management_corrupt - if True, item is corrupt
If not True, get item's shape
Look for any file attached to shape
If file is in shape, item is in house
If item is in house and not corrupt, get the filename
Otherwise filename is "N/A"
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

def get_shape_file(vs, vs_auth, item_id):
	url = f'{vs}API/item/{item_id}?content=shape&tag=original'
	headers = {
		'Accept': 'application/xml',
		'Authorization': vs_auth
	}
	response = xml_prep(requests.get(url, headers=headers))
	shape_file = response.find('shape/containerComponent/file')
	return shape_file

def get_system_metadata_value(vs,vs_auth,item_id,field):
	# for ungrouped fields
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
	# for fields in groups
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
		if metadata_value == '' or metadata_value == None:
			return 'NONE'
		else:
			return metadata_value
	except AttributeError:
		# doesn't have the field
		return 'NONE'

def main(environment,proxy_config_file,script_file_name):
	user = getpass.getuser()
	logging.info(f'{environment}: COMMENCING: {script_file_name} executed by {user}')
	proxy_config = ET.parse(proxy_config_file)
	vs,vs_auth = get_variables_from_config(environment,proxy_config)
	resultsfile = open("InHouse_notCorrupt.csv", "w+")
	resultsfile.write('Checksum,Item ID,Corrupt,In House,Filename\r')
	item_list = open('itemIds.txt', 'r')
	for item in item_list:
		item = item.strip()
		corrupt = get_group_metadata_value(vs, vs_auth, item, 'media_management_corrupt')
		if corrupt and corrupt.lower() == 'true':
			print(f'{item} IS CORRUPT')
			corrupt = 'True'
			shape_presence = 'N/A'
			filename = 'N/A'
			checksum = 'N/A'
		else:
			print(f'{item} IS NOT CORRUPT')
			corrupt = 'False'
			shape_presence = get_shape_file(vs, vs_auth, item)
			if shape_presence is None:
				print(f'{item} IS NOT IN HOUSE')
				shape_presence = 'False'
				filename = 'N/A'
				checksum = 'N/A'
			else:
				print(f'{item} IS IN HOUSE')
				shape_presence = 'True'
				filename = get_system_metadata_value(vs,vs_auth,item,'originalFilename')
				checksum = get_group_metadata_value(vs,vs_auth,item,'original_shape_mi_original_shape_mi_md5_hash')
				print(f'{filename}\n{checksum}\n')
		resultsfile.write(f'{checksum},{item},{corrupt},{shape_presence},{filename}\r')
	print('Finished.')

main(environment,proxy_config_file,script_file_name)
exit(0)