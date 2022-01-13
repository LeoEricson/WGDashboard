"""
< WGDashboard > - Copyright(C) 2021 Donald Zou [https://github.com/donaldzou]
Under Apache-2.0 License
"""

# TODO: Testing migrate to sqlite
import sqlite3
from flask import g
import configparser
import hashlib
import ipaddress
import json
# Python Built-in Library
import os
import secrets
import subprocess
import time
import re
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from operator import itemgetter
# PIP installed library
import ifcfg
from flask import Flask, request, render_template, redirect, url_for, session, jsonify
from flask_qrcode import QRcode
from icmplib import ping, traceroute

# Import other python files
from util import regex_match, check_DNS, check_Allowed_IPs, check_remote_endpoint, \
    check_IP_with_range, clean_IP_with_range

# Dashboard Version
DASHBOARD_VERSION = 'v3.0'
# WireGuard configuration path
WG_CONF_PATH = None
# Dashboard Config Name
configuration_path = os.getenv('CONFIGURATION_PATH', '.')
DB_PATH = os.path.join(configuration_path, 'db')
if not os.path.isdir(DB_PATH):
    os.mkdir(DB_PATH)
DASHBOARD_CONF = os.path.join(configuration_path, 'wg-dashboard.ini')
# Upgrade Required
UPDATE = None
# Flask App Configuration
app = Flask("WGDashboard")
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 5206928
app.secret_key = secrets.token_urlsafe(16)
app.config['TEMPLATES_AUTO_RELOAD'] = True
# Enable QR Code Generator
QRcode(app)


def connect_db():
    return sqlite3.connect(os.path.join(configuration_path, 'db', 'wgdashboard.db'))


# TODO use class and object oriented programming

# Read / Write Dashboard Config File
def get_dashboard_conf():
    """Dashboard Configuration Related

    :return: A config parser object
    :rtype: configparser.ConfigParser
    """

    config = configparser.ConfigParser(strict=False)
    config.read(DASHBOARD_CONF)
    return config


def set_dashboard_conf(config):
    """Configuration writer

    :param config: A config parser object
    :type config: configparser.ConfigParser
    """

    with open(DASHBOARD_CONF, "w", encoding='utf-8') as conf_object:
        config.write(conf_object)


# Get all keys from a configuration
def get_conf_peer_key(config_name):
    """Get the peers keys of wireguard interface.

    :param config_name: Name of WG interface
    :type config_name: str
    :return: Return list of peers keys or text if configuration not running
    :rtype: list, str
    """

    try:
        peers_keys = subprocess.run(f"wg show {config_name} peers",
                                    check=True, shell=True, capture_output=True).stdout
        peers_keys = peers_keys.decode("UTF-8").split()
        return peers_keys
    except subprocess.CalledProcessError:
        return config_name + " is not running."


# Get numbers of connected peer of a configuration
def get_conf_running_peer_number(config_name):
    """Get number of running peers on wireguard interface.

    :param config_name: Name of WG interface
    :type config_name: str
    :return: Number of running peers, or test if configuration not running
    :rtype: int, str
    """

    running = 0
    # Get latest handshakes
    try:
        data_usage = subprocess.run(f"wg show {config_name} latest-handshakes",
                                    check=True, shell=True, capture_output=True).stdout
    except subprocess.CalledProcessError:
        return "stopped"
    data_usage = data_usage.decode("UTF-8").split()
    count = 0
    now = datetime.now()
    time_delta = timedelta(minutes=2)
    for _ in range(int(len(data_usage) / 2)):
        minus = now - datetime.fromtimestamp(int(data_usage[count + 1]))
        if minus < time_delta:
            running += 1
        count += 2
    return running


# TODO use modules for working with ini(configparser or wireguard)
# Read [Interface] section from configuration file
def read_conf_file_interface(config_name):
    """Get interface settings.
    
    :param config_name: Name of WG interface
    :type config_name: str
    :return: Dictionary with interface settings
    :rtype: dict
    """

    conf_location = WG_CONF_PATH + "/" + config_name + ".conf"
    with open(conf_location, 'r', encoding='utf-8') as file_object:
        file = file_object.read().split("\n")
        data = {}
        for i in file:
            if not regex_match("#(.*)", i):
                if len(i) > 0:
                    if i != "[Interface]":
                        tmp = re.split(r'\s*=\s*', i, 1)
                        if len(tmp) == 2:
                            data[tmp[0]] = tmp[1]
    return data


# TODO use modules for working with ini(configparser or wireguard)
# Read the whole configuration file
def read_conf_file(config_name):
    """Get configurations from file of wireguard interface.

    :param config_name: Name of WG interface
    :type config_name: str
    :return: Dictionary with interface and peers settings
    :rtype: dict
    """

    # Read Configuration File Start
    conf_location = WG_CONF_PATH + "/" + config_name + ".conf"
    f = open(conf_location, 'r')
    file = f.read().split("\n")
    conf_peer_data = {
        "Interface": {},
        "Peers": []
    }
    peers_start = 0
    for i in range(len(file)):
        if not regex_match("#(.*)", file[i]) and regex_match(";(.*)", file[i]):
            if file[i] == "[Peer]":
                peers_start = i
                break
            else:
                if len(file[i]) > 0:
                    if file[i] != "[Interface]":
                        tmp = re.split(r'\s*=\s*', file[i], 1)
                        if len(tmp) == 2:
                            conf_peer_data['Interface'][tmp[0]] = tmp[1]
    conf_peers = file[peers_start:]
    peer = -1
    for i in conf_peers:
        if not regex_match("#(.*)", i) and not regex_match(";(.*)", i):
            if i == "[Peer]":
                peer += 1
                conf_peer_data["Peers"].append({})
            elif peer > -1:
                if len(i) > 0:
                    tmp = re.split('\s*=\s*', i, 1)
                    if len(tmp) == 2:
                        conf_peer_data["Peers"][peer][tmp[0]] = tmp[1]

    f.close()
    # Read Configuration File End
    return conf_peer_data


# Get the latest handshake from all peers of a configuration
def get_latest_handshake(config_name):
    # Get latest handshakes
    try:
        data_usage = subprocess.run(f"wg show {config_name} latest-handshakes",
                                    check=True, shell=True, capture_output=True).stdout
    except subprocess.CalledProcessError:
        return "stopped"
    data_usage = data_usage.decode("UTF-8").split()
    count = 0
    now = datetime.now()
    time_delta = timedelta(minutes=2)
    for _ in range(int(len(data_usage) / 2)):
        minus = now - datetime.fromtimestamp(int(data_usage[count + 1]))
        if minus < time_delta:
            status = "running"
        else:
            status = "stopped"
        if int(data_usage[count + 1]) > 0:
            g.cur.execute("UPDATE %s SET latest_handshake = '%s', status = '%s' WHERE id='%s'"
                          % (config_name, str(minus).split(".", maxsplit=1)[0], status, data_usage[count]))
        else:
            g.cur.execute("UPDATE %s SET latest_handshake = '(None)', status = '%s' WHERE id='%s'"
                          % (config_name, status, data_usage[count]))
        count += 2
    return None


# Get transfer from all peers of a configuration
def get_transfer(config_name):
    # Get transfer
    try:
        data_usage = subprocess.run(f"wg show {config_name} transfer",
                                    check=True, shell=True, capture_output=True).stdout
    except subprocess.CalledProcessError:
        return "stopped"
    data_usage = data_usage.decode("UTF-8").split("\n")
    final = []
    for i in data_usage:
        final.append(i.split("\t"))
    data_usage = final
    for i in range(len(data_usage)):
        cur_i = g.cur.execute(
            "SELECT total_receive, total_sent, cumu_receive, cumu_sent, status FROM %s WHERE id='%s'"
            % (config_name, data_usage[i][0])).fetchall()
        if len(cur_i) > 0:
            total_sent = cur_i[0][1]
            total_receive = cur_i[0][0]
            cur_total_sent = round(int(data_usage[i][2]) / (1024 ** 3), 4)
            cur_total_receive = round(int(data_usage[i][1]) / (1024 ** 3), 4)
            if cur_i[0][4] == "running":
                if total_sent <= cur_total_sent and total_receive <= cur_total_receive:
                    total_sent = cur_total_sent
                    total_receive = cur_total_receive
                else:
                    cumulative_receive = cur_i[0][2] + total_receive
                    cumulative_sent = cur_i[0][3] + total_sent
                    g.cur.execute("UPDATE %s SET cumu_receive = %f, cumu_sent = %f, cumu_data = %f WHERE id = '%s'" %
                                  (config_name, round(cumulative_receive, 4), round(cumulative_sent, 4),
                                   round(cumulative_sent + cumulative_receive, 4), data_usage[i][0]))
                    total_sent = 0
                    total_receive = 0
                g.cur.execute("UPDATE %s SET total_receive = %f, total_sent = %f, total_data = %f WHERE id = '%s'" %
                              (config_name, round(total_receive, 4), round(total_sent, 4),
                               round(total_receive + total_sent, 4), data_usage[i][0]))
    return None


# Get endpoint from all peers of a configuration
def get_endpoint(config_name):
    # Get endpoint
    try:
        data_usage = subprocess.run(f"wg show {config_name} endpoints",
                                    check=True, shell=True, capture_output=True).stdout
    except subprocess.CalledProcessError:
        return "stopped"
    data_usage = data_usage.decode("UTF-8").split()
    count = 0
    for _ in range(int(len(data_usage) / 2)):
        g.cur.execute("UPDATE " + config_name + " SET endpoint = '%s' WHERE id = '%s'"
                      % (data_usage[count + 1], data_usage[count]))
        count += 2
    return None


# Get allowed ips from all peers of a configuration
def get_allowed_ip(conf_peer_data, config_name):
    # Get allowed ip
    for i in conf_peer_data["Peers"]:
        g.cur.execute("UPDATE " + config_name + " SET allowed_ip = '%s' WHERE id = '%s'"
                      % (i.get('AllowedIPs', '(None)'), i["PublicKey"]))


# Look for new peers from WireGuard
def get_all_peers_data(config_name):
    conf_peer_data = read_conf_file(config_name)
    config = get_dashboard_conf()
    failed_index = []
    for i in range(len(conf_peer_data['Peers'])):
        if "PublicKey" in conf_peer_data['Peers'][i].keys():
            result = g.cur.execute(
                "SELECT * FROM %s WHERE id='%s'" % (config_name, conf_peer_data['Peers'][i]["PublicKey"])).fetchall()
            if len(result) == 0:
                new_data = {
                    "id": conf_peer_data['Peers'][i]['PublicKey'],
                    "private_key": "",
                    "DNS": config.get("Peers", "peer_global_DNS"),
                    "endpoint_allowed_ip": config.get("Peers", "peer_endpoint_allowed_ip"),
                    "name": "",
                    "total_receive": 0,
                    "total_sent": 0,
                    "total_data": 0,
                    "endpoint": "N/A",
                    "status": "stopped",
                    "latest_handshake": "N/A",
                    "allowed_ip": "N/A",
                    "cumu_receive": 0,
                    "cumu_sent": 0,
                    "cumu_data": 0,
                    "traffic": [],
                    "mtu": config.get("Peers", "peer_mtu"),
                    "keepalive": config.get("Peers", "peer_keep_alive"),
                    "remote_endpoint": config.get("Peers", "remote_endpoint"),
                    "preshared_key": ""
                }
                if "PresharedKey" in conf_peer_data['Peers'][i].keys():
                    new_data["preshared_key"] = conf_peer_data['Peers'][i]["PresharedKey"]
                sql = f"""
                INSERT INTO {config_name} 
                    VALUES (:id, :private_key, :DNS, :endpoint_allowed_ip, :name, :total_receive, :total_sent, 
                    :total_data, :endpoint, :status, :latest_handshake, :allowed_ip, :cumu_receive, :cumu_sent, 
                    :cumu_data, :mtu, :keepalive, :remote_endpoint, :preshared_key);
                """
                g.cur.execute(sql, new_data)
        else:
            print("Trying to parse a peer doesn't have public key...")
            failed_index.append(i)

    for i in failed_index:
        conf_peer_data['Peers'].pop(i)
    # Remove peers no longer exist in WireGuard configuration file
    db_key = list(map(lambda a: a[0], g.cur.execute("SELECT id FROM %s" % config_name)))
    wg_key = list(map(lambda a: a['PublicKey'], conf_peer_data['Peers']))
    for i in db_key:
        if i not in wg_key:
            g.cur.execute("DELETE FROM %s WHERE id = '%s'" % (config_name, i))
    tic = time.perf_counter()
    get_latest_handshake(config_name)
    get_transfer(config_name)
    get_endpoint(config_name)
    get_allowed_ip(conf_peer_data, config_name)
    toc = time.perf_counter()
    print(f"Finish fetching data in {toc - tic:0.4f} seconds")


# Search for peers
def get_peers(config_name, search, sort_t):
    """Get all peers.

    :param config_name: Name of WG interface
    :type config_name: str
    :param search: Search string
    :type search: str
    :param sort_t: TODO
    :type sort_t: str
    :return: TODO
    """
    tic = time.perf_counter()
    col = g.cur.execute("PRAGMA table_info(" + config_name + ")").fetchall()
    col = [a[1] for a in col]
    get_all_peers_data(config_name)
    if len(search) == 0:
        data = g.cur.execute("SELECT * FROM " + config_name).fetchall()
        result = [{col[i]: data[k][i] for i in range(len(col))} for k in range(len(data))]
    else:
        sql = "SELECT * FROM " + config_name + " WHERE name LIKE '%" + search + "%'"
        data = g.cur.execute(sql).fetchall()
        result = [{col[i]: data[k][i] for i in range(len(col))} for k in range(len(data))]
    if sort_t == "allowed_ip":
        result = sorted(result, key=lambda d: ipaddress.ip_network(
            "0.0.0.0/0" if d[sort_t].split(",")[0] == "(None)" else d[sort_t].split(",")[0]))
    else:
        result = sorted(result, key=lambda d: d[sort_t])
    toc = time.perf_counter()
    print(f"Finish fetching peers in {toc - tic:0.4f} seconds")
    return result


# Get configuration public key
def get_conf_pub_key(config_name):
    """Get public key for configuration.

    :param config_name: Name of WG interface
    :type config_name: str
    :return: Return public key or empty string
    :rtype: str
    """

    try:
        conf = configparser.ConfigParser(strict=False)
        conf.read(WG_CONF_PATH + "/" + config_name + ".conf")
        pri = conf.get("Interface", "PrivateKey")
        pub = subprocess.run(f"echo '{pri}' | wg pubkey", check=True, shell=True, capture_output=True).stdout
        conf.clear()
        return pub.decode().strip("\n")
    except configparser.NoSectionError:
        return ""


# Get configuration listen port
def get_conf_listen_port(config_name):
    """Get listen port number.

    :param config_name: Name of WG interface
    :type config_name: str
    :return: Return number of port or empty string
    :rtype: str
    """

    conf = configparser.ConfigParser(strict=False)
    conf.read(WG_CONF_PATH + "/" + config_name + ".conf")
    port = ""
    try:
        port = conf.get("Interface", "ListenPort")
    except (configparser.NoSectionError, configparser.NoOptionError):
        if get_conf_status(config_name) == "running":
            port = subprocess.run(f"wg show {config_name} listen-port",
                                  check=True, shell=True, capture_output=True).stdout
            port = port.decode("UTF-8")
    conf.clear()
    return port


# Get configuration total data
def get_conf_total_data(config_name):
    data = g.cur.execute("SELECT total_sent, total_receive, cumu_sent, cumu_receive FROM " + config_name)
    upload_total = 0
    download_total = 0
    for i in data.fetchall():
        upload_total += i[0]
        download_total += i[1]
        upload_total += i[2]
        download_total += i[3]
    total = round(upload_total + download_total, 4)
    upload_total = round(upload_total, 4)
    download_total = round(download_total, 4)
    return [total, upload_total, download_total]


# Get configuration status
def get_conf_status(config_name):
    ifconfig = dict(ifcfg.interfaces().items())

    return "running" if config_name in ifconfig.keys() else "stopped"


# Get all configuration as a list
def get_conf_list():
    """Get all wireguard interfaces with status.

    :return: Return a list of dicts with interfaces and its statuses
    :rtype: list
    """

    conf = []
    for i in os.listdir(WG_CONF_PATH):
        if regex_match("^(.{1,}).(conf)$", i):
            i = i.replace('.conf', '')
            create_table = f"""
                CREATE TABLE IF NOT EXISTS {i} (
                    id VARCHAR NOT NULL, private_key VARCHAR NULL, DNS VARCHAR NULL, 
                    endpoint_allowed_ip VARCHAR NULL, name VARCHAR NULL, total_receive FLOAT NULL, 
                    total_sent FLOAT NULL, total_data FLOAT NULL, endpoint VARCHAR NULL, 
                    status VARCHAR NULL, latest_handshake VARCHAR NULL, allowed_ip VARCHAR NULL, 
                    cumu_receive FLOAT NULL, cumu_sent FLOAT NULL, cumu_data FLOAT NULL, mtu INT NULL, 
                    keepalive INT NULL, remote_endpoint VARCHAR NULL, preshared_key VARCHAR NULL, 
                    PRIMARY KEY (id)
                )
            """
            g.cur.execute(create_table)
            temp = {"conf": i, "status": get_conf_status(i), "public_key": get_conf_pub_key(i)}
            if temp['status'] == "running":
                temp['checked'] = 'checked'
            else:
                temp['checked'] = ""
            conf.append(temp)
    if len(conf) > 0:
        conf = sorted(conf, key=itemgetter('conf'))
    return conf


# Generate private key
def gen_private_key():
    subprocess.run('wg genkey > private_key.txt && wg pubkey < private_key.txt > public_key.txt', shell=True)
    with open('private_key.txt', encoding='utf-8') as file_object:
        private_key = file_object.readline().strip()
    with open('public_key.txt', encoding='utf-8') as file_object:
        public_key = file_object.readline().strip()
    data = {"private_key": private_key, "public_key": public_key}
    return data


# Generate public key
def gen_public_key(private_key):
    """Generate the public key.

    :param private_key: Pricate key
    :type private_key: str
    :return: Return dict with public key or error message
    :rtype: dict
    """

    with open('private_key.txt', 'w', encoding='utf-8') as file_object:
        file_object.write(private_key)
    try:
        subprocess.check_output("wg pubkey < private_key.txt > public_key.txt", shell=True)
        with open('public_key.txt', encoding='utf-8') as file_object:
            public_key = file_object.readline().strip()
        os.remove('private_key.txt')
        os.remove('public_key.txt')
        return {"status": 'success', "msg": "", "data": public_key}
    except subprocess.CalledProcessError:
        os.remove('private_key.txt')
        return {"status": 'failed', "msg": "Key is not the correct length or format", "data": ""}


# Check if private key and public key match
def f_check_key_match(private_key, public_key, config_name):
    """TODO

    :param private_key: Private key
    :type private_key: str
    :param public_key: Public key
    :type public_key: str
    :param config_name: Name of WG interface
    :type config_name: str
    :return: Return dictionary with status
    :rtype: dict
    """

    result = gen_public_key(private_key)
    if result['status'] == 'failed':
        return result
    else:
        sql = "SELECT * FROM " + config_name + " WHERE id = ?"
        match = g.cur.execute(sql, (result['data'],)).fetchall()
        if len(match) != 1 or result['data'] != public_key:
            return {'status': 'failed', 'msg': 'Please check your private key, it does not match with the public key.'}
        else:
            return {'status': 'success'}


# Check if there is repeated allowed IP
def check_repeat_allowed_ip(public_key, ip, config_name):
    peer = g.cur.execute("SELECT COUNT(*) FROM " + config_name + " WHERE id = ?", (public_key,)).fetchone()
    if peer[0] != 1:
        return {'status': 'failed', 'msg': 'Peer does not exist'}
    else:
        existed_ip = g.cur.execute("SELECT COUNT(*) FROM " +
                                   config_name + " WHERE id != ? AND allowed_ip LIKE '" + ip + "/%'", (public_key,)) \
            .fetchone()
        if existed_ip[0] != 0:
            return {'status': 'failed', 'msg': "Allowed IP already taken by another peer."}
        else:
            return {'status': 'success'}


def f_available_ips(config_name):
    config_interface = read_conf_file_interface(config_name)
    if "Address" in config_interface:
        existed = []
        conf_address = config_interface['Address']
        address = conf_address.split(',')
        for i in address:
            add, sub = i.split("/")
            existed.append(ipaddress.ip_address(add))
        peers = g.cur.execute("SELECT allowed_ip FROM " + config_name).fetchall()
        for i in peers:
            add = i[0].split(",")
            for k in add:
                a, s = k.split("/")
                existed.append(ipaddress.ip_address(a.strip()))
        available = list(ipaddress.ip_network(address[0], False).hosts())
        for i in existed:
            try:
                available.remove(i)
            except ValueError:
                pass
        available = [str(i) for i in available]
        return available
    else:
        return []


"""
Flask Functions
"""


@app.teardown_request
def close_DB(exception):
    if hasattr(g, 'db'):
        g.db.commit()
        g.db.close()


# Before request
@app.before_request
def auth_req():
    if getattr(g, 'db', None) is None:
        g.db = connect_db()
        g.cur = g.db.cursor()
    conf = get_dashboard_conf()
    req = conf.get("Server", "auth_req")
    session['update'] = UPDATE
    session['dashboard_version'] = DASHBOARD_VERSION
    if req == "true":
        if '/static/' not in request.path and \
                request.endpoint != "signin" and \
                request.endpoint != "signout" and \
                request.endpoint != "auth" and \
                "username" not in session:
            print("User not signed in - Attempted access: " + str(request.endpoint))
            if request.endpoint != "index":
                session['message'] = "You need to sign in first!"
            else:
                session['message'] = ""
            conf.clear()
            return redirect(url_for("signin"))
    else:
        if request.endpoint in ['signin', 'signout', 'auth', 'settings', 'update_acct', 'update_pwd',
                                'update_app_ip_port', 'update_wg_conf_path']:
            conf.clear()
            return redirect(url_for("index"))
    conf.clear()
    return None


"""
Sign In / Sign Out
"""


# Sign In
@app.route('/signin', methods=['GET'])
def signin():
    """Sign in request.

    :return: TODO
    :rtype: TODO
    """

    message = ""
    if "message" in session:
        message = session['message']
        session.pop("message")
    return render_template('signin.html', message=message)


# Sign Out
@app.route('/signout', methods=['GET'])
def signout():
    """Sign out request.

    :return: TODO
    :rtype: TODO
    """

    if "username" in session:
        session.pop("username")
    message = "Sign out successfully!"
    return render_template('signin.html', message=message)


# Authentication
@app.route('/auth', methods=['POST'])
def auth():
    """Authentication request.

    :return: TODO
    :rtype: TODO
    """

    config = get_dashboard_conf()
    password = hashlib.sha256(request.form['password'].encode())
    if password.hexdigest() == config["Account"]["password"] \
            and request.form['username'] == config["Account"]["username"]:
        session['username'] = request.form['username']
        config.clear()
        return redirect(url_for("index"))

    session['message'] = "Username or Password is incorrect."
    config.clear()
    return redirect(url_for("signin"))


@app.route('/', methods=['GET'])
def index():
    """Index Page Related.

    :return: TODO
    :rtype: TODO
    """
    return render_template('index.html', conf=get_conf_list())


# Setting Page
@app.route('/settings', methods=['GET'])
def settings():
    """Setting Page Related.

    :return: TODO
    :rtype: TODO
    """
    message = ""
    status = ""
    config = get_dashboard_conf()
    if "message" in session and "message_status" in session:
        message = session['message']
        status = session['message_status']
        session.pop("message")
        session.pop("message_status")
    required_auth = config.get("Server", "auth_req")
    return render_template('settings.html', conf=get_conf_list(), message=message, status=status,
                           app_ip=config.get("Server", "app_ip"), app_port=config.get("Server", "app_port"),
                           required_auth=required_auth, wg_conf_path=config.get("Server", "wg_conf_path"),
                           peer_global_DNS=config.get("Peers", "peer_global_DNS"),
                           peer_endpoint_allowed_ip=config.get("Peers", "peer_endpoint_allowed_ip"),
                           peer_mtu=config.get("Peers", "peer_mtu"),
                           peer_keepalive=config.get("Peers", "peer_keep_alive"),
                           peer_remote_endpoint=config.get("Peers", "remote_endpoint"))


# Update account username
@app.route('/update_acct', methods=['POST'])
def update_acct():
    """Change account user name.

    :return: TODO
    :rtype: TODO
    """

    if len(request.form['username']) == 0:
        session['message'] = "Username cannot be empty."
        session['message_status'] = "danger"
        return redirect(url_for("settings"))
    config = get_dashboard_conf()
    config.set("Account", "username", request.form['username'])
    try:
        set_dashboard_conf(config)
        config.clear()
        session['message'] = "Username update successfully!"
        session['message_status'] = "success"
        session['username'] = request.form['username']
        return redirect(url_for("settings"))
    except Exception:
        session['message'] = "Username update failed."
        session['message_status'] = "danger"
        config.clear()
        return redirect(url_for("settings"))


# Update peer default settting
@app.route('/update_peer_default_config', methods=['POST'])
def update_peer_default_config():
    """Change default configurations for peers.

    :return: TODO
    :rtype: TODO
    """

    config = get_dashboard_conf()
    if len(request.form['peer_endpoint_allowed_ip']) == 0 or \
            len(request.form['peer_global_DNS']) == 0 or \
            len(request.form['peer_remote_endpoint']) == 0:
        session['message'] = "Please fill in all required boxes."
        session['message_status'] = "danger"
        config.clear()
        return redirect(url_for("settings"))
    # Check DNS Format
    dns_addresses = request.form['peer_global_DNS']
    if not check_DNS(dns_addresses):
        session['message'] = "Peer DNS Format Incorrect."
        session['message_status'] = "danger"
        config.clear()
        return redirect(url_for("settings"))
    dns_addresses = dns_addresses.replace(" ", "").split(',')
    dns_addresses = ",".join(dns_addresses)
    # Check Endpoint Allowed IPs
    ip = request.form['peer_endpoint_allowed_ip']
    if not check_Allowed_IPs(ip):
        session['message'] = "Peer Endpoint Allowed IPs Format Incorrect. " \
                             "Example: 192.168.1.1/32 or 192.168.1.1/32,192.168.1.2/32"
        session['message_status'] = "danger"
        config.clear()
        return redirect(url_for("settings"))
    # Check MTU Format
    if not len(request.form['peer_mtu']) > 0 or not request.form['peer_mtu'].isdigit():
        session['message'] = "MTU format is incorrect."
        session['message_status'] = "danger"
        config.clear()
        return redirect(url_for("settings"))
    # Check keepalive Format
    if not len(request.form['peer_keep_alive']) > 0 or not request.form['peer_keep_alive'].isdigit():
        session['message'] = "Persistent keepalive format is incorrect."
        session['message_status'] = "danger"
        config.clear()
        return redirect(url_for("settings"))
    # Check peer remote endpoint
    if not check_remote_endpoint(request.form['peer_remote_endpoint']):
        session['message'] = "Peer Remote Endpoint format is incorrect. It can only be a valid " \
                             "IP address or valid domain (without http:// or https://). "
        session['message_status'] = "danger"
        config.clear()
        return redirect(url_for("settings"))
    config.set("Peers", "remote_endpoint", request.form['peer_remote_endpoint'])
    config.set("Peers", "peer_keep_alive", request.form['peer_keep_alive'])
    config.set("Peers", "peer_mtu", request.form['peer_mtu'])
    config.set("Peers", "peer_endpoint_allowed_ip", ','.join(clean_IP_with_range(ip)))
    config.set("Peers", "peer_global_DNS", dns_addresses)
    try:
        set_dashboard_conf(config)
        session['message'] = "Peer Default Settings update successfully!"
        session['message_status'] = "success"
        config.clear()
        return redirect(url_for("settings"))
    except Exception:
        session['message'] = "Peer Default Settings update failed."
        session['message_status'] = "danger"
        config.clear()
        return redirect(url_for("settings"))


# Update dashboard password
@app.route('/update_pwd', methods=['POST'])
def update_pwd():
    """Change account password.

    :return: TODO
    :rtype: TODO
    """

    config = get_dashboard_conf()
    if hashlib.sha256(request.form['currentpass'].encode()).hexdigest() == config.get("Account", "password"):
        if hashlib.sha256(request.form['newpass'].encode()).hexdigest() == hashlib.sha256(
                request.form['repnewpass'].encode()).hexdigest():
            config.set("Account", "password", hashlib.sha256(request.form['repnewpass'].encode()).hexdigest())
            try:
                set_dashboard_conf(config)
                session['message'] = "Password update successfully!"
                session['message_status'] = "success"
                config.clear()
                return redirect(url_for("settings"))
            except Exception:
                session['message'] = "Password update failed"
                session['message_status'] = "danger"
                config.clear()
                return redirect(url_for("settings"))
        else:
            session['message'] = "Your New Password does not match."
            session['message_status'] = "danger"
            config.clear()
            return redirect(url_for("settings"))
    else:
        session['message'] = "Your Password does not match."
        session['message_status'] = "danger"
        config.clear()
        return redirect(url_for("settings"))


# Update dashboard IP and port
@app.route('/update_app_ip_port', methods=['POST'])
def update_app_ip_port():
    """Change port number of dashboard.
    """

    config = get_dashboard_conf()
    config.set("Server", "app_ip", request.form['app_ip'])
    config.set("Server", "app_port", request.form['app_port'])
    set_dashboard_conf(config)
    config.clear()
    os.system('bash wgd.sh restart')


# Update WireGuard configuration file path
@app.route('/update_wg_conf_path', methods=['POST'])
def update_wg_conf_path():
    """Change path to dashboard configuration.
    """

    config = get_dashboard_conf()
    config.set("Server", "wg_conf_path", request.form['wg_conf_path'])
    set_dashboard_conf(config)
    config.clear()
    session['message'] = "WireGuard Configuration Path Update Successfully!"
    session['message_status'] = "success"
    os.system('bash wgd.sh restart')


# Update configuration sorting
@app.route('/update_dashboard_sort', methods=['POST'])
def update_dashbaord_sort():
    """Configuration Page Related
    """

    config = get_dashboard_conf()
    data = request.get_json()
    sort_tag = ['name', 'status', 'allowed_ip']
    if data['sort'] in sort_tag:
        config.set("Server", "dashboard_sort", data['sort'])
    else:
        config.set("Server", "dashboard_sort", 'status')
    set_dashboard_conf(config)
    config.clear()
    return "true"


# Update configuration refresh interval
@app.route('/update_dashboard_refresh_interval', methods=['POST'])
def update_dashboard_refresh_interval():
    """Change the refresh time.

    :return: Return text with result
    :rtype: str
    """

    preset_interval = ["5000", "10000", "30000", "60000"]
    if request.form["interval"] in preset_interval:
        config = get_dashboard_conf()
        config.set("Server", "dashboard_refresh_interval", str(request.form['interval']))
        set_dashboard_conf(config)
        config.clear()
        return "true"
    else:
        return "false"


# Configuration Page
@app.route('/configuration/<config_name>', methods=['GET'])
def configuration(config_name):
    """Show wireguard interface view.

    :param config_name: Name of WG interface
    :type config_name: str
    :return: TODO
    :rtype: TODO
    """

    config = get_dashboard_conf()
    conf_data = {
        "name": config_name,
        "status": get_conf_status(config_name),
        "checked": ""
    }
    if conf_data['status'] == "stopped":
        conf_data['checked'] = "nope"
    else:
        conf_data['checked'] = "checked"
    config_list = get_conf_list()
    if config_name not in [conf['conf'] for conf in config_list]:
        return render_template('index.html', conf=get_conf_list())

    refresh_interval = int(config.get("Server", "dashboard_refresh_interval"))
    dns_address = config.get("Peers", "peer_global_DNS")
    allowed_ip = config.get("Peers", "peer_endpoint_allowed_ip")
    peer_mtu = config.get("Peers", "peer_MTU")
    peer_keep_alive = config.get("Peers", "peer_keep_alive")
    config.clear()
    return render_template('configuration.html', conf=get_conf_list(), conf_data=conf_data,
                           dashboard_refresh_interval=refresh_interval,
                           DNS=dns_address,
                           endpoint_allowed_ip=allowed_ip,
                           title=config_name,
                           mtu=peer_mtu,
                           keep_alive=peer_keep_alive)


# Get configuration details
@app.route('/get_config/<config_name>', methods=['GET'])
def get_conf(config_name):
    """Get configuration setting of wireguard interface.

    :param config_name: Name of WG interface
    :type config_name: str
    :return: TODO
    :rtype: TODO
    """

    config_interface = read_conf_file_interface(config_name)
    search = request.args.get('search')
    if len(search) == 0:
        search = ""
    search = urllib.parse.unquote(search)
    config = get_dashboard_conf()
    sort = config.get("Server", "dashboard_sort")
    peer_display_mode = config.get("Peers", "peer_display_mode")
    wg_ip = config.get("Peers", "remote_endpoint")
    if "Address" not in config_interface:
        conf_address = "N/A"
    else:
        conf_address = config_interface['Address']
    conf_data = {
        "peer_data": get_peers(config_name, search, sort),
        "name": config_name,
        "status": get_conf_status(config_name),
        "total_data_usage": get_conf_total_data(config_name),
        "public_key": get_conf_pub_key(config_name),
        "listen_port": get_conf_listen_port(config_name),
        "running_peer": get_conf_running_peer_number(config_name),
        "conf_address": conf_address,
        "wg_ip": wg_ip,
        "sort_tag": sort,
        "dashboard_refresh_interval": int(config.get("Server", "dashboard_refresh_interval")),
        "peer_display_mode": peer_display_mode
    }
    if conf_data['status'] == "stopped":
        conf_data['checked'] = "nope"
    else:
        conf_data['checked'] = "checked"
    config.clear()
    return jsonify(conf_data)



# Turn on / off a configuration
@app.route('/switch/<config_name>', methods=['GET'])
def switch(config_name):
    """On/off the wireguard interface.

    :param config_name: Name of WG interface
    :type config_name: str
    :return: TODO
    :rtype: TODO
    """

    if "username" not in session:
        print("User not logged in")
        return redirect(url_for("signin"))
    status = get_conf_status(config_name)
    if status == "running":
        try:
            subprocess.run("wg-quick down " + config_name,
                           check=True, shell=True, capture_output=True).stdout
        except subprocess.CalledProcessError:
            return redirect('/')
    elif status == "stopped":
        try:
            subprocess.run("wg-quick up " + config_name,
                           check=True, shell=True, capture_output=True).stdout
        except subprocess.CalledProcessError:
            return redirect('/')
    return redirect(request.referrer)


@app.route('/add_peer_bulk/<config_name>', methods=['POST'])
def add_peer_bulk(config_name):
    data = request.get_json()
    keys = data['keys']
    endpoint_allowed_ip = data['endpoint_allowed_ip']
    dns_addresses = data['DNS']
    enable_preshared_key = data["enable_preshared_key"]
    amount = data['amount']
    config_interface = read_conf_file_interface(config_name)
    if "Address" not in config_interface:
        return "Configuration must have an IP address."
    if not amount.isdigit() or int(amount) < 1:
        return "Amount must be integer larger than 0"
    amount = int(amount)
    if not check_DNS(dns_addresses):
        return "DNS formate is incorrect. Example: 1.1.1.1"
    if not check_Allowed_IPs(endpoint_allowed_ip):
        return "Endpoint Allowed IPs format is incorrect."
    if len(data['MTU']) == 0 or not data['MTU'].isdigit():
        return "MTU format is not correct."
    if len(data['keep_alive']) == 0 or not data['keep_alive'].isdigit():
        return "Persistent Keepalive format is not correct."
    ips = f_available_ips(config_name)
    if amount > len(ips):
        return f"Cannot create more than {len(ips)} peers."
    wg_command = ["wg", "set", config_name]
    sql_command = []
    for i in range(amount):
        keys[i]['name'] = f"{config_name}_{datetime.now().strftime('%m%d%Y%H%M%S')}_Peer_#_{(i + 1)}"
        wg_command.append("peer")
        wg_command.append(keys[i]['publicKey'])
        keys[i]['allowed_ips'] = ips.pop(0)
        if enable_preshared_key:
            keys[i]['psk_file'] = f"{keys[i]['name']}.txt"
            f = open(keys[i]['psk_file'], "w+")
            f.write(keys[i]['presharedKey'])
            f.close()
            wg_command.append("preshared-key")
            wg_command.append(keys[i]['psk_file'])
        else:
            keys[i]['psk_file'] = ""
        wg_command.append("allowed-ips")
        wg_command.append(keys[i]['allowed_ips'])
        update = ["UPDATE ", config_name, " SET name = '", keys[i]['name'],
                  "', private_key = '", keys[i]['privateKey'], "', DNS = '", dns_addresses,
                  "', endpoint_allowed_ip = '", endpoint_allowed_ip, "' WHERE id = '", keys[i]['publicKey'], "'"]
        sql_command.append(update)
    try:
        status = subprocess.check_output(" ".join(wg_command), shell=True, stderr=subprocess.STDOUT)
        status = subprocess.check_output("wg-quick save " + config_name, shell=True, stderr=subprocess.STDOUT)
        get_all_peers_data(config_name)
        if enable_preshared_key:
            for i in keys:
                os.remove(i['psk_file'])
        for i in range(len(sql_command)):
            sql_command[i] = "".join(sql_command[i])
        g.cur.executescript("; ".join(sql_command))
        return "true"
    except subprocess.CalledProcessError as exc:
        return exc.output.strip()


# Add peer
@app.route('/add_peer/<config_name>', methods=['POST'])
def add_peer(config_name):
    data = request.get_json()
    public_key = data['public_key']
    allowed_ips = data['allowed_ips']
    endpoint_allowed_ip = data['endpoint_allowed_ip']
    dns_addresses = data['DNS']
    enable_preshared_key = data["enable_preshared_key"]
    preshared_key = data['preshared_key']
    keys = get_conf_peer_key(config_name)
    if len(public_key) == 0 or len(dns_addresses) == 0 or len(allowed_ips) == 0 or len(endpoint_allowed_ip) == 0:
        return "Please fill in all required box."
    if not isinstance(keys, list):
        return config_name + " is not running."
    if public_key in keys:
        return "Public key already exist."
    check_dup_ip = g.cur.execute(
        "SELECT COUNT(*) FROM " + config_name + " WHERE allowed_ip LIKE '" + allowed_ips + "/%'", ) \
        .fetchone()
    if check_dup_ip[0] != 0:
        return "Allowed IP already taken by another peer."
    if not check_DNS(dns_addresses):
        return "DNS formate is incorrect. Example: 1.1.1.1"
    if not check_Allowed_IPs(endpoint_allowed_ip):
        return "Endpoint Allowed IPs format is incorrect."
    if len(data['MTU']) == 0 or not data['MTU'].isdigit():
        return "MTU format is not correct."
    if len(data['keep_alive']) == 0 or not data['keep_alive'].isdigit():
        return "Persistent Keepalive format is not correct."
    try:
        if enable_preshared_key:
            now = str(datetime.now().strftime("%m%d%Y%H%M%S"))
            f_name = now + "_tmp_psk.txt"
            print(f_name)
            f = open(f_name, "w+")
            f.write(preshared_key)
            f.close()
            status = subprocess.check_output(
                f"wg set {config_name} peer {public_key} allowed-ips {allowed_ips} preshared-key {f_name}",
                shell=True, stderr=subprocess.STDOUT)
            os.remove(f_name)
        elif not enable_preshared_key:
            status = subprocess.check_output(f"wg set {config_name} peer {public_key} allowed-ips {allowed_ips}",
                                             shell=True, stderr=subprocess.STDOUT)
        status = subprocess.check_output("wg-quick save " + config_name, shell=True, stderr=subprocess.STDOUT)
        get_all_peers_data(config_name)
        sql = "UPDATE " + config_name + " SET name = ?, private_key = ?, DNS = ?, endpoint_allowed_ip = ? WHERE id = ?"
        g.cur.execute(sql, (data['name'], data['private_key'], data['DNS'], endpoint_allowed_ip, public_key))
        return "true"
    except subprocess.CalledProcessError as exc:
        return exc.output.strip()


# Remove peer
@app.route('/remove_peer/<config_name>', methods=['POST'])
def remove_peer(config_name):
    """Remove peer.

    :param config_name: Name of WG interface
    :type config_name: str
    :return: Return result of action or recommendations
    :rtype: str
    """

    if get_conf_status(config_name) == "stopped":
        return "Your need to turn on " + config_name + " first."
    data = request.get_json()
    delete_keys = data['peer_ids']
    keys = get_conf_peer_key(config_name)
    if not isinstance(keys, list):
        return config_name + " is not running."
    else:
        sql_command = []
        wg_command = ["wg", "set", config_name]
        for delete_key in delete_keys:
            if delete_key not in keys:
                return "This key does not exist"
            sql_command.append("DELETE FROM " + config_name + " WHERE id = '" + delete_key + "';")
            wg_command.append("peer")
            wg_command.append(delete_key)
            wg_command.append("remove")
        try:
            remove_wg = subprocess.check_output(" ".join(wg_command),
                                                shell=True, stderr=subprocess.STDOUT)
            save_wg = subprocess.check_output(f"wg-quick save {config_name}", shell=True, stderr=subprocess.STDOUT)
            g.cur.executescript(' '.join(sql_command))
            g.db.commit()
        except subprocess.CalledProcessError as exc:
            return exc.output.strip()
        return "true"


# Save peer settings
@app.route('/save_peer_setting/<config_name>', methods=['POST'])
def save_peer_setting(config_name):
    """Save peer configuration.

    :param config_name: Name of WG interface
    :type config_name: str
    :return: Return status of action and text with recommendations
    :rtype: TODO
    """

    data = request.get_json()
    id = data['id']
    name = data['name']
    private_key = data['private_key']
    dns_addresses = data['DNS']
    allowed_ip = data['allowed_ip']
    endpoint_allowed_ip = data['endpoint_allowed_ip']
    preshared_key = data['preshared_key']
    check_peer_exist = g.cur.execute("SELECT COUNT(*) FROM " + config_name + " WHERE id = ?", (id,)).fetchone()
    if check_peer_exist[0] == 1:
        check_ip = check_repeat_allowed_ip(id, allowed_ip, config_name)
        if not check_IP_with_range(endpoint_allowed_ip):
            return jsonify({"status": "failed", "msg": "Endpoint Allowed IPs format is incorrect."})
        if not check_DNS(dns_addresses):
            return jsonify({"status": "failed", "msg": "DNS format is incorrect."})
        if len(data['MTU']) == 0 or not data['MTU'].isdigit():
            return jsonify({"status": "failed", "msg": "MTU format is not correct."})
        if len(data['keep_alive']) == 0 or not data['keep_alive'].isdigit():
            return jsonify({"status": "failed", "msg": "Persistent Keepalive format is not correct."})
        if private_key != "":
            check_key = f_check_key_match(private_key, id, config_name)
            if check_key['status'] == "failed":
                return jsonify(check_key)
        if check_ip['status'] == "failed":
            return jsonify(check_ip)
        try:
            tmp_psk = open("tmp_edit_psk.txt", "w+")
            tmp_psk.write(preshared_key)
            tmp_psk.close()
            change_psk = subprocess.run(f"wg set {config_name} peer {id} preshared-key tmp_edit_psk.txt",
                                        shell=True, check=True, stderr=subprocess.STDOUT)
            if change_psk.decode("UTF-8") != "":
                return jsonify({"status": "failed", "msg": change_psk.decode("UTF-8")})
            if allowed_ip == "":
                allowed_ip = '""'
            allowed_ip = allowed_ip.replace(" ", "")
            change_ip = subprocess.run(f"wg set {config_name} peer {id} allowed-ips {allowed_ip}",
                                       shell=True, check=True, stderr=subprocess.STDOUT)
            subprocess.run(f'wg-quick save {config_name}', shell=True, check=True, stderr=subprocess.STDOUT)
            if change_ip.decode("UTF-8") != "":
                return jsonify({"status": "failed", "msg": change_ip.decode("UTF-8")})
            sql = "UPDATE " + config_name + " SET name = ?, private_key = ?, DNS = ?, endpoint_allowed_ip = ?, mtu = ?, keepalive = ?, preshared_key = ? WHERE id = ?"
            g.cur.execute(sql, (name, private_key, dns_addresses, endpoint_allowed_ip, data["MTU"],
                                data["keep_alive"], preshared_key, id))
            return jsonify({"status": "success", "msg": ""})
        except subprocess.CalledProcessError as exc:
            return jsonify({"status": "failed", "msg": str(exc.output.decode("UTF-8").strip())})
    else:
        return jsonify({"status": "failed", "msg": "This peer does not exist."})


# Get peer settings
@app.route('/get_peer_data/<config_name>', methods=['POST'])
def get_peer_name(config_name):
    """Get peer settings.

    :param config_name: Name of WG interface
    :type config_name: str
    :return: Return settings of peer
    :rtype: TODO
    """

    data = request.get_json()
    peer_id = data['id']
    result = g.cur.execute(
        "SELECT name, allowed_ip, DNS, private_key, endpoint_allowed_ip, mtu, keepalive, preshared_key FROM "
        + config_name + " WHERE id = ?", (peer_id,)).fetchall()
    data = {"name": result[0][0], "allowed_ip": result[0][1], "DNS": result[0][2],
            "private_key": result[0][3], "endpoint_allowed_ip": result[0][4],
            "mtu": result[0][5], "keep_alive": result[0][6], "preshared_key": result[0][7]}
    return jsonify(data)


# Return available IPs
@app.route('/available_ips/<config_name>', methods=['GET'])
def available_ips(config_name):
    return jsonify(f_available_ips(config_name))


# Generate a private key
@app.route('/generate_peer', methods=['GET'])
def generate_peer():
    """Generate the private key for peer.

    :return: Return dict with private, public and preshared keys
    :rtype: TODO
    """

    return jsonify(gen_private_key())


# Generate a public key from a private key
@app.route('/generate_public_key', methods=['POST'])
def generate_public_key():
    """Generate the public key.

    :return: Return dict with public key or error message
    :rtype: TODO
    """

    data = request.get_json()
    private_key = data['private_key']
    return jsonify(gen_public_key(private_key))


# Check if both key match
@app.route('/check_key_match/<config_name>', methods=['POST'])
def check_key_match(config_name):
    """TODO

    :param config_name: Name of WG interface
    :type config_name: str
    :return: Return dictionary with status
    :rtype: TODO
    """

    data = request.get_json()
    private_key = data['private_key']
    public_key = data['public_key']
    return jsonify(f_check_key_match(private_key, public_key, config_name))


@app.route("/qrcode/<config_name>", methods=['GET'])
def generate_qrcode(config_name):
    peer_id = request.args.get('id')
    get_peer = g.cur.execute(
        "SELECT private_key, allowed_ip, DNS, mtu, endpoint_allowed_ip, keepalive, preshared_key FROM "
        + config_name + " WHERE id = ?", (peer_id,)).fetchall()
    config = get_dashboard_conf()
    if len(get_peer) == 1:
        peer = get_peer[0]
        if peer[0] != "":
            public_key = get_conf_pub_key(config_name)
            listen_port = get_conf_listen_port(config_name)
            endpoint = config.get("Peers", "remote_endpoint") + ":" + listen_port
            private_key = peer[0]
            allowed_ip = peer[1]
            dns_addresses = peer[2]
            mtu_value = peer[3]
            endpoint_allowed_ip = peer[4]
            keepalive = peer[5]
            preshared_key = peer[6]

            result = "[Interface]\nPrivateKey = " + private_key + "\nAddress = " + allowed_ip + "\nMTU = " \
                     + str(mtu_value) + "\nDNS = " + dns_addresses + "\n\n[Peer]\nPublicKey = " + public_key \
                     + "\nAllowedIPs = " + endpoint_allowed_ip + "\nPersistentKeepalive = " \
                     + str(keepalive) + "\nEndpoint = " + endpoint
            if preshared_key != "":
                result += "\nPresharedKey = " + preshared_key
            return render_template("qrcode.html", i=result)
    else:
        return redirect("/configuration/" + config_name)


# Download all configuration file
@app.route('/download_all/<config_name>', methods=['GET'])
def download_all(config_name):
    get_peer = g.cur.execute(
        "SELECT private_key, allowed_ip, DNS, mtu, endpoint_allowed_ip, keepalive, preshared_key, name FROM "
        + config_name + " WHERE private_key != ''").fetchall()
    config = get_dashboard_conf()
    data = []
    public_key = get_conf_pub_key(config_name)
    listen_port = get_conf_listen_port(config_name)
    endpoint = config.get("Peers", "remote_endpoint") + ":" + listen_port
    for peer in get_peer:
        private_key = peer[0]
        allowed_ip = peer[1]
        dns_addresses = peer[2]
        mtu_value = peer[3]
        endpoint_allowed_ip = peer[4]
        keepalive = peer[5]
        preshared_key = peer[6]
        filename = peer[7]
        if len(filename) == 0:
            filename = "Untitled_Peer"
        else:
            filename = peer[7]
            # Clean filename
            illegal_filename = [".", ",", "/", "?", "<", ">", "\\", ":", "*", '|' '\"', "com1", "com2", "com3",
                                "com4", "com5", "com6", "com7", "com8", "com9", "lpt1", "lpt2", "lpt3", "lpt4",
                                "lpt5", "lpt6", "lpt7", "lpt8", "lpt9", "con", "nul", "prn"]
            for i in illegal_filename:
                filename = filename.replace(i, "")
            if len(filename) == 0:
                filename = "Untitled_Peer"
            filename = "".join(filename.split(' '))
        filename = filename + "_" + config_name
        psk = ""
        if preshared_key != "":
            psk = "\nPresharedKey = " + preshared_key

        return_data = "[Interface]\nPrivateKey = " + private_key + "\nAddress = " + allowed_ip + "\nDNS = " + \
                      dns_addresses + "\nMTU = " + str(mtu_value) + "\n\n[Peer]\nPublicKey = " + \
                      public_key + "\nAllowedIPs = " + endpoint_allowed_ip + "\nEndpoint = " + \
                      endpoint + "\nPersistentKeepalive = " + str(keepalive) + psk
        data.append({"filename": f"{filename}.conf", "content": return_data})
    return jsonify({"status": True, "peers": data, "filename": f"{config_name}.zip"})


# Download configuration file
@app.route('/download/<config_name>', methods=['GET'])
def download(config_name):
    peer_id = request.args.get('id')
    get_peer = g.cur.execute(
        "SELECT private_key, allowed_ip, DNS, mtu, endpoint_allowed_ip, keepalive, preshared_key, name FROM "
        + config_name + " WHERE id = ?", (peer_id,)).fetchall()
    config = get_dashboard_conf()
    if len(get_peer) == 1:
        peer = get_peer[0]
        if peer[0] != "":
            public_key = get_conf_pub_key(config_name)
            listen_port = get_conf_listen_port(config_name)
            endpoint = config.get("Peers", "remote_endpoint") + ":" + listen_port
            private_key = peer[0]
            allowed_ip = peer[1]
            dns_addresses = peer[2]
            mtu_value = peer[3]
            endpoint_allowed_ip = peer[4]
            keepalive = peer[5]
            preshared_key = peer[6]
            filename = peer[7]
            if len(filename) == 0:
                filename = "Untitled_Peer"
            else:
                filename = peer[7]
                # Clean filename
                illegal_filename = [".", ",", "/", "?", "<", ">", "\\", ":", "*", '|' '\"', "com1", "com2", "com3",
                                    "com4", "com5", "com6", "com7", "com8", "com9", "lpt1", "lpt2", "lpt3", "lpt4",
                                    "lpt5", "lpt6", "lpt7", "lpt8", "lpt9", "con", "nul", "prn"]
                for i in illegal_filename:
                    filename = filename.replace(i, "")
                if len(filename) == 0:
                    filename = "Untitled_Peer"
                filename = "".join(filename.split(' '))
            filename = filename + "_" + config_name
            psk = ""
            if preshared_key != "":
                psk = "\nPresharedKey = " + preshared_key

            return_data = "[Interface]\nPrivateKey = " + private_key + "\nAddress = " + allowed_ip + "\nDNS = " + \
                          dns_addresses + "\nMTU = " + str(mtu_value) + "\n\n[Peer]\nPublicKey = " + \
                          public_key + "\nAllowedIPs = " + endpoint_allowed_ip + "\nEndpoint = " + \
                          endpoint + "\nPersistentKeepalive = " + str(keepalive) + psk

            return jsonify({"status": True, "filename": f"{filename}.conf", "content": return_data})
    return jsonify({"status": False, "filename": "", "content": ""})


# Switch peer display mode
@app.route('/switch_display_mode/<mode>', methods=['GET'])
def switch_display_mode(mode):
    """Change display view style.

    :param mode: Mode name
    :type mode: str
    :return: Return text with result
    :rtype: str
    """

    if mode in ['list', 'grid']:
        config = get_dashboard_conf()
        config.set("Peers", "peer_display_mode", mode)
        set_dashboard_conf(config)
        config.clear()
        return "true"
    return "false"


"""
Dashboard Tools Related
"""


# Get all IP for ping
@app.route('/get_ping_ip', methods=['POST'])
def get_ping_ip():
    """Get ips for network testing.

    :return: TODO
    :rtype: TODO
    """

    config = request.form['config']
    peers = g.cur.execute("SELECT id, name, allowed_ip, endpoint FROM " + config).fetchall()
    html = ""
    for i in peers:
        html += '<optgroup label="' + i[1] + ' - ' + i[0] + '">'
        allowed_ip = str(i[2]).split(",")
        for k in allowed_ip:
            k = k.split("/")
            if len(k) == 2:
                html += "<option value=" + k[0] + ">" + k[0] + "</option>"
        endpoint = str(i[3]).split(":")
        if len(endpoint) == 2:
            html += "<option value=" + endpoint[0] + ">" + endpoint[0] + "</option>"
        html += "</optgroup>"
    return html


# Ping IP
@app.route('/ping_ip', methods=['POST'])
def ping_ip():
    """Execute ping command.

    :return: Return text with result
    :rtype: str
    """

    try:
        result = ping('' + request.form['ip'] + '', count=int(request.form['count']), privileged=True, source=None)
        returnjson = {
            "address": result.address,
            "is_alive": result.is_alive,
            "min_rtt": result.min_rtt,
            "avg_rtt": result.avg_rtt,
            "max_rtt": result.max_rtt,
            "package_sent": result.packets_sent,
            "package_received": result.packets_received,
            "package_loss": result.packet_loss
        }
        if returnjson['package_loss'] == 1.0:
            returnjson['package_loss'] = returnjson['package_sent']
        return jsonify(returnjson)
    except Exception:
        return "Error"


# Traceroute IP
@app.route('/traceroute_ip', methods=['POST'])
def traceroute_ip():
    """Execute ping traceroute command.

    :return: Return text with result
    :rtype: str
    """

    try:
        result = traceroute('' + request.form['ip'] + '', first_hop=1, max_hops=30, count=1, fast=True)
        returnjson = []
        last_distance = 0
        for hop in result:
            if last_distance + 1 != hop.distance:
                returnjson.append({"hop": "*", "ip": "*", "avg_rtt": "", "min_rtt": "", "max_rtt": ""})
            returnjson.append({"hop": hop.distance, "ip": hop.address, "avg_rtt": hop.avg_rtt, "min_rtt": hop.min_rtt,
                               "max_rtt": hop.max_rtt})
            last_distance = hop.distance
        return jsonify(returnjson)
    except Exception:
        return "Error"


"""
Dashboard Initialization
"""


def init_dashboard():
    """Create dashboard default configuration.
    """

    # Set Default INI File
    if not os.path.isfile(DASHBOARD_CONF):
        open(DASHBOARD_CONF, "w+").close()
    config = get_dashboard_conf()
    # Defualt dashboard account setting
    if "Account" not in config:
        config['Account'] = {}
    if "username" not in config['Account']:
        config['Account']['username'] = 'admin'
    if "password" not in config['Account']:
        config['Account']['password'] = '8c6976e5b5410415bde908bd4dee15dfb167a9c873fc4bb8a81f6f2ab448a918'
    # Defualt dashboard server setting
    if "Server" not in config:
        config['Server'] = {}
    if 'wg_conf_path' not in config['Server']:
        config['Server']['wg_conf_path'] = '/etc/wireguard'
    # TODO: IPv6 for the app IP might need to configure with Gunicorn...
    if 'app_ip' not in config['Server']:
        config['Server']['app_ip'] = '0.0.0.0'
    if 'app_port' not in config['Server']:
        config['Server']['app_port'] = '10086'
    if 'auth_req' not in config['Server']:
        config['Server']['auth_req'] = 'true'
    if 'version' not in config['Server'] or config['Server']['version'] != DASHBOARD_VERSION:
        config['Server']['version'] = DASHBOARD_VERSION
    if 'dashboard_refresh_interval' not in config['Server']:
        config['Server']['dashboard_refresh_interval'] = '60000'
    if 'dashboard_sort' not in config['Server']:
        config['Server']['dashboard_sort'] = 'status'
    # Default dashboard peers setting
    if "Peers" not in config:
        config['Peers'] = {}
    if 'peer_global_DNS' not in config['Peers']:
        config['Peers']['peer_global_DNS'] = '1.1.1.1'
    if 'peer_endpoint_allowed_ip' not in config['Peers']:
        config['Peers']['peer_endpoint_allowed_ip'] = '0.0.0.0/0'
    if 'peer_display_mode' not in config['Peers']:
        config['Peers']['peer_display_mode'] = 'grid'
    if 'remote_endpoint' not in config['Peers']:
        config['Peers']['remote_endpoint'] = ifcfg.default_interface()['inet']
    if 'peer_MTU' not in config['Peers']:
        config['Peers']['peer_MTU'] = "1420"
    if 'peer_keep_alive' not in config['Peers']:
        config['Peers']['peer_keep_alive'] = "21"
    set_dashboard_conf(config)
    config.clear()


def check_update():
    """Dashboard check update

    :return: Retunt text with result
    :rtype: str
    """
    config = get_dashboard_conf()
    data = urllib.request.urlopen("https://api.github.com/repos/donaldzou/WGDashboard/releases").read()
    output = json.loads(data)
    release = []
    for i in output:
        if not i["prerelease"]:
            release.append(i)
    if config.get("Server", "version") == release[0]["tag_name"]:
        result = "false"
    else:
        result = "true"

    return result


if __name__ == "__main__":
    init_dashboard()
    UPDATE = check_update()
    configuration_settings = get_dashboard_conf()
    app_ip = configuration_settings.get("Server", "app_ip")
    app_port = int(configuration_settings.get("Server", "app_port"))
    WG_CONF_PATH = configuration_settings.get("Server", "wg_conf_path")
    configuration_settings.clear()
    app.run(host=app_ip, debug=False, port=app_port)
