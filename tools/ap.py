from wifiConfig import __main__ as wc
access_point_config = {"wlan": 'wlan0', "inet": None, "ip":'192.168.45.1', "netmask": '255.255.255.0', "ssid": 'MyMetarMap', "password": '1234567890'}
flask_app_config = {"host": "0.0.0.0", "port": "8080"}


myWifiConfig = wc.WifiConfApp(access_point_config, flask_app_config)
myWifiConfig.start()
