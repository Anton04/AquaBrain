env DISPLAY=:0 XAUTHORITY=/home/anton/.Xauthority \
  chromium \
    --user-data-dir=/tmp/chromium-aquaview \
    --kiosk --start-fullscreen --app=http://127.0.0.1:8100/ --incognito \
    --noerrdialogs --disable-infobars --disable-session-crashed-bubble \
    --password-store=basic \
    --disable-features=PasswordManager
