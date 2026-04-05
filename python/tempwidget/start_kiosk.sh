env DISPLAY=:0 XAUTHORITY=/home/anton/.Xauthority \
  chromium \
    --user-data-dir=/tmp/chromium-kiosk \
    --kiosk --incognito \
    --noerrdialogs --disable-infobars --disable-session-crashed-bubble \
    --password-store=basic \
    --disable-features=PasswordManager \
    http://127.0.0.1:8000/
