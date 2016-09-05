
install_deps:
	sudo -H pip3 install -r requirements.txt

install:
	install -m 755 -T mdvrd.py /usr/bin/mdvrd
	install -m 644 assets/mdvrd.service /lib/systemd/system/
	@echo "now call systemctl daemon-reload"
	@echo ".. enable service via: systemctl enable mdvrd.service"
	@echo ".. start service via:  systemctl start mdvrd.service"
	@echo ".. status via:         systemctl status mdvrd.service"
	@echo ".. log info via:       journalctl -u mdvrd.service"

uninstall:
	rm -rf /usr/bin/mdvrd
	rm -rf /lib/systemd/system/mdvrd.service
