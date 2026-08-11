#!/usr/bin/env bash
# Boots the app the way Render will: production env vars, collectstatic,
# migrate, then a real gunicorn process answering real requests.
set -u
cd "$(dirname "$0")/.."

export RENDER_EXTERNAL_HOSTNAME="vocabulary-tester-backend.onrender.com"
export SECRET_KEY="simulated-production-secret-key-not-real"
export FRONTEND_ORIGINS="https://eartester.netlify.app"
export DATABASE_URL="sqlite:///$(pwd)/prod_sim.sqlite3"
unset DEBUG

pass=0; fail=0
check () { if [ "$2" = "0" ]; then echo "  PASS  $1"; pass=$((pass+1)); else echo "  FAIL  $1 ${3:-}"; fail=$((fail+1)); fi }

rm -f prod_sim.sqlite3
rm -rf staticfiles

echo "--- settings resolve in production mode"
python -c "
import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE','server.settings')
django.setup()
from django.conf import settings
assert settings.DEBUG is False, 'DEBUG should be off'
assert 'vocabulary-tester-backend.onrender.com' in settings.ALLOWED_HOSTS, settings.ALLOWED_HOSTS
assert 'https://eartester.netlify.app' in settings.CORS_ALLOWED_ORIGINS, settings.CORS_ALLOWED_ORIGINS
assert 'https://eartester.netlify.app' in settings.CSRF_TRUSTED_ORIGINS, settings.CSRF_TRUSTED_ORIGINS
assert settings.SECURE_PROXY_SSL_HEADER, 'proxy header not trusted'
print('   DEBUG', settings.DEBUG, '| hosts', settings.ALLOWED_HOSTS)
"
check "production settings resolve" $?

echo "--- missing SECRET_KEY is refused"
SECRET_KEY="" python -c "
import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE','server.settings')
try:
    django.setup(); raise SystemExit('should have refused to start')
except RuntimeError as e:
    print('  ', e); raise SystemExit(0)
" >/dev/null 2>&1
check "blank SECRET_KEY stops the boot" $?

echo "--- build command"
python manage.py collectstatic --no-input > /tmp/collect.log 2>&1
check "collectstatic" $? "$(tail -2 /tmp/collect.log)"
python manage.py migrate > /tmp/migrate.log 2>&1
check "migrate" $? "$(tail -3 /tmp/migrate.log)"
python manage.py check --deploy > /tmp/deploycheck.log 2>&1
check "manage.py check --deploy" $? "$(tail -5 /tmp/deploycheck.log)"

echo "--- gunicorn serves the app"
gunicorn server.wsgi:application --bind 127.0.0.1:8111 --workers 1 --log-file /tmp/gunicorn.log --access-logfile /dev/null &
GPID=$!
sleep 5

code=$(curl -s -o /tmp/body.txt -w "%{http_code}" -H "Host: vocabulary-tester-backend.onrender.com" -H "X-Forwarded-Proto: https" http://127.0.0.1:8111/api/decks/)
[ "$code" = "200" ]; check "GET /api/decks/ returns 200" $? "got $code: $(head -c 200 /tmp/body.txt)"
grep -q '"decks"' /tmp/body.txt; check "response is the deck list" $?

echo "--- CORS for the Netlify frontend"
hdrs=$(curl -s -D - -o /dev/null -H "Host: vocabulary-tester-backend.onrender.com" -H "X-Forwarded-Proto: https" -H "Origin: https://eartester.netlify.app" http://127.0.0.1:8111/api/decks/)
echo "$hdrs" | grep -qi "access-control-allow-origin: https://eartester.netlify.app"; check "allows the Netlify origin" $?

pre=$(curl -s -o /dev/null -w "%{http_code}" -X OPTIONS -H "Host: vocabulary-tester-backend.onrender.com" -H "X-Forwarded-Proto: https" -H "Origin: https://eartester.netlify.app" -H "Access-Control-Request-Method: PATCH" http://127.0.0.1:8111/api/words/1/mark/)
[ "$pre" = "204" ]; check "preflight for PATCH answered" $? "got $pre"

other=$(curl -s -D - -o /dev/null -H "Host: vocabulary-tester-backend.onrender.com" -H "X-Forwarded-Proto: https" -H "Origin: https://evil.example.com" http://127.0.0.1:8111/api/decks/)
echo "$other" | grep -qi "access-control-allow-origin"; [ $? -ne 0 ]; check "an unlisted origin is not allowed" $?

echo "--- admin static files are served"
admincode=$(curl -s -o /dev/null -w "%{http_code}" -H "Host: vocabulary-tester-backend.onrender.com" -H "X-Forwarded-Proto: https" http://127.0.0.1:8111/static/admin/css/base.css)
[ "$admincode" = "200" ]; check "whitenoise serves admin CSS" $? "got $admincode"

echo "--- a full round trip through the API"
python - <<'PY'
import io, json, urllib.request, uuid, pathlib
base = "http://127.0.0.1:8111/api"
hdr = {"Host": "vocabulary-tester-backend.onrender.com", "X-Forwarded-Proto": "https"}
path = pathlib.Path("../sample-decks/0001_field_notes.csv")
b = uuid.uuid4().hex
body = (f'--{b}\r\nContent-Disposition: form-data; name="name"\r\n\r\n{path.name}\r\n'.encode()
        + f'--{b}\r\nContent-Disposition: form-data; name="file"; filename="{path.name}"\r\nContent-Type: text/csv\r\n\r\n'.encode()
        + path.read_bytes() + f'\r\n--{b}--\r\n'.encode())
req = urllib.request.Request(base + "/decks/", data=body,
        headers={**hdr, "Content-Type": f"multipart/form-data; boundary={b}"})
deck = json.loads(urllib.request.urlopen(req).read())["deck"]
req = urllib.request.Request(base + "/sessions/", data=json.dumps({"deck": deck["id"]}).encode(),
        headers={**hdr, "Content-Type": "application/json"})
payload = json.loads(urllib.request.urlopen(req).read())
w = payload["words"][0]
answers = {k: w[k] for k in ("word","synonym1","synonym2","antonym1","antonym2")}
req = urllib.request.Request(base + f"/sessions/{payload['session']['id']}/answer/",
        data=json.dumps({"index": 0, "answers": answers, "elapsed_ms": 4200}).encode(),
        headers={**hdr, "Content-Type": "application/json"})
reply = json.loads(urllib.request.urlopen(req).read())
assert reply["correct"] == 5, reply
assert reply["total_ms"] == 4200, reply
print("   uploaded, started a run, answered a word, timing recorded")
PY
check "upload → session → answer works over gunicorn" $?

kill $GPID 2>/dev/null; wait $GPID 2>/dev/null
rm -f prod_sim.sqlite3
echo
echo "$pass passed, $fail failed"
[ "$fail" = "0" ] || tail -20 /tmp/gunicorn.log
exit $([ "$fail" = "0" ] && echo 0 || echo 1)
