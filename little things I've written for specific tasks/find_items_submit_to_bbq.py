#!/usr/bin/python3
import requests
import xml.etree.ElementTree as ET
import time
import sys
import logging
import os
import getpass

# create list of items that match search criteria
# put metadata to each

'''
comment
comment
comment still going
'''

search_doc = '''
<ItemSearchDocument xmlns="http://xml.vidispine.com/schema/vidispine">
    <intervals>generic</intervals>
    <operator operation="AND">
            <field>
                <name>file_information_vendor_folder</name>
                <value>CARNEGIE</value>
            </field>
             <field>
                <name>mediaType</name>
                <value>image</value>
            </field>
        </operator>
</ItemSearchDocument>
'''

metadata_doc = '''
<MetadataDocument xmlns="http://xml.vidispine.com/schema/vidispine">
    <timespan end="+INF" start="-INF">
        <group>
            <name>indab</name>
            <field>
                <name>indab_qc_trigger</name>
                <value>True</value>
            </field>
        </group>
    </timespan>
</MetadataDocument>
'''


def get_env():
	# this function asks the user to enter the environment name
	print()
	env = input('Enter the environment we are submitting items to qc on: (dev, uat, prod)\n\n')
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
		print('Arguement passed to script was not an environment name: dev, uat, or prod')
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

def get_items(vs,vs_auth,search_doc):
	url = vs+'API/item'
	headers = {
		'Accept': 'application/xml',
		'Content-type': 'application/xml',
		'Authorization': vs_auth
	}
	data = search_doc
	response = requests.request("PUT", url, headers=headers, data=data)
	item_list_doc = xml_prep(response)
	hits = int(item_list_doc.find('hits').text)
	print('There are %s hits.' %str(hits))
	number = 300
	first = 1
	item_list = []
	while True:
		url = vs+'API/item;first=%s;number=%s' %(str(first),str(number))
		response = requests.request("PUT", url, headers=headers, data=data)
		items = xml_prep(response)
		for item in items.findall('item'):
			item_id = item.attrib['id']
			item_list.append(item_id)
		#first = first + number
		break
	return item_list

def put_vs_metadata(vs,vs_auth,item_id,metadata_doc):
	url = vs+'API/item/%s/metadata' %(item_id)
	headers = {
		'Content-Type': 'application/xml',
		'Authorization': vs_auth
	}
	response = requests.request("PUT", url, headers=headers, data=metadata_doc)
	if response.status_code >= 300:
		logging.error('%s: put vs metadata status: %s content: %s' % (environment,str(response.status_code),response.content))
		exit(1)
	else:
		logging.info('%s: put vs metadata status: %s' % (environment,str(response.status_code)))
		return True

def main(environment,proxy_config_file,search_doc,script_file_name,metadata_doc):
	user = getpass.getuser()
	logging.info('%s: COMMENCING: %s executed by %s' % (environment,script_file_name,user))
	proxy_config = ET.parse(proxy_config_file)
	vs,vs_auth = get_variables_from_config(environment,proxy_config)
	# make a list of items
	item_list = get_items(vs,vs_auth,search_doc)
	# for each item in list, put new metadata
	for item in item_list:
		put_vs_metadata(vs,vs_auth,item,metadata_doc)
	return True

main(environment,proxy_config_file,search_doc,script_file_name,metadata_doc)
exit(0)

