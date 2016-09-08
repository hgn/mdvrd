
install_deps:
	sudo -H pip3 install -r requirements.txt

help:
	@echo
	@echo "now call sudo systemctl daemon-reload"
	@echo ".. enable service via: sudo systemctl enable mdvrd.service"
	@echo ".. start service via:  sudo systemctl start mdvrd.service"
	@echo ".. status via:         sudo systemctl status mdvrd.service"
	@echo ".. log info via:       sudo journalctl -u mdvrd.service"

install:
	install -m 755 -T mdvrd.py /usr/bin/mdvrd
	mkdir -p /etc/mdvrd
	install -m 644 -T mdvrd-conf.json /etc/mdvrd/mdvrd.json
	install -m 644 assets/mdvrd.service /lib/systemd/system/

uninstall:
	rm -rf /usr/bin/mdvrd
	rm -rf /etc/mdvrd
	rm -rf /lib/systemd/system/mdvrd.service
