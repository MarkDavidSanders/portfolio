#!/usr/bin/python3
import requests
import xml.etree.ElementTree as ET
import sys
import logging
import os
import getpass

# use external txt file as list of item IDs
# pull collection IDs from metadata of each item, print to collectionIds.txt
# using collectionIds.txt as search doc, pull up collections for each item
# if a given item in the collection has a role of ateme-caption, print that item ID to file
# if not, check for caption role
# if neither ateme-caption nor captions exist and embedded_captions = true, print "embedded"
# if none of the above, print "Shit outta luck, buddy"

field_name = 'itemId'
field_name2 = '__collection'

def get_env():
	# this function asks the user to enter the environment name
	print()
	env = input('\n\nEnter the environment we are searching: (dev, uat, prod)\n\n')
	env = env.lower()
	if env == 'dev' or env == 'uat' or env == 'prod':
		print()
		print('We will be working on: %s.' % env)
		print()
		return env
	else:
		print()
		print('oops try again. must be dev, uat, or prod')
		print()
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
		print('Argument passed: %s' % sys.argv[1])
		print()
		environment = get_env()

# set up  other global variables:
# /Users/keithkoby/Library/CloudStorage/Box-Box/Engineering/scripts/vidispine/find_items_submit_to_bbq/find_items_submit_to_bbq.py

script_path = sys.argv[0]
# get the script file name from the path
script_file_name = script_path[script_path.rfind('/')+1:]
script_file_name_no_extention = script_file_name[0:script_file_name.rfind('.')]
log_file = script_path.replace(script_file_name,script_file_name_no_extention+'.log')
proxy_config_file = script_path.replace(script_file_name,'proxy_config.xml')

# logging setup

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

def get_item_metadata(vs,vs_auth,item_id,field_name):
	url = vs+'API/item/%s/metadata;field=%s' % (item_id,field_name)
	headers = {
		'Accept': 'application/xml',
		'Authorization': vs_auth
	}
	response = requests.request("GET", url, headers=headers)
	metadata_doc = xml_prep(response)
	if metadata_doc.find('item/metadata/timespan/field/value') is None:
		metadata = 'N/A'
	else:
		metadata = metadata_doc.find('item/metadata/timespan/field/value').text
	return metadata

def get_caption_id_from_collection(vs,vs_auth,collection_id):
	url = vs+'API/collection/%s' % (collection_id)
	headers = {
		'Authorization': vs_auth
	}
	response = requests.get(url, headers=headers)
	collection_doc = xml_prep(response)
	collection_items = collection_doc.findall('content')
	for item in collection_items:
		if item.find('metadata/field/value').text == 'ateme-caption':
			caption_id = 'MCC %s' % (item.find('id').text)
			return caption_id

def main(environment,proxy_config_file,script_file_name,field_name):
	user = getpass.getuser()
	logging.info('%s: COMMENCING: %s executed by %s' % (environment,script_file_name,user))
	proxy_config = ET.parse(proxy_config_file)
	vs,vs_auth = get_variables_from_config(environment,proxy_config)
	captionfile = open("captionIds.txt", "w+")
	collection_list = open('collectionIds.txt', 'r')
	for x in collection_list:
		caption_id = get_caption_id_from_collection(vs,vs_auth,x.strip())
		print(caption_id)
		captionfile.write(str(caption_id))
		captionfile.write('\r')
	captionfile.close()
	return True

main(environment,proxy_config_file,script_file_name,field_name)
exit(0)

