# restaurant-qr-menu

[![tests](https://github.com/SamruddhBorker/restaurant-qr-menu/actions/workflows/tests.yml/badge.svg)](https://github.com/SamruddhBorker/restaurant-qr-menu/actions/workflows/tests.yml)

A QR-code menu for restaurants and cafés where **sold-out dishes update live**.
Customers scan a table QR code and see the menu on their phone. Staff tap
"−1 sold" after each order, and the menu shows "Only 3 left" and then
"Sold out" within seconds. No reprinting, no app to install.

**The problem:** printed menus go out of date. Customers order dishes the
kitchen has run out of, and waiters spend the shift apologising.

- Python 3.9+, **standard library only**, SQLite storage, no build step
- Includes its own **QR code generator**, so no extra packages and no external QR service
- Works offline on your restaurant's Wi-Fi

## Try it

```bash
python server.py
```

Open <http://127.0.0.1:8000> for the customer menu and
<http://127.0.0.1:8000/staff> for staff. A staff PIN is printed at startup.
To keep the same PIN, set `STAFF_PIN` in your environment first.

To let phones on your Wi-Fi connect:

```bash
python server.py --host 0.0.0.0
```

It prints the address to use (for example `http://192.168.1.5:8000/`).

## For customers

- Menu grouped by category, with veg/non-veg markers and prices
- **Live** stock badges ("Only 3 left", "Sold out"), refreshed every 5 seconds
- Veg-only and hide-sold-out filters
- Table number from the QR code (`?t=5` shows "Table 5")
- Light and dark mode, mobile first

## For staff (`/staff`)

- Sign in with the PIN
- **−1 sold** per dish, **Set stock**, **Mark sold out / Back in stock**
- Add, edit and delete dishes; blank stock means unlimited
- **Table QR codes**: enter your menu address and number of tables, then print the sheet

## Make it yours

Edit [`config.json`](config.json): restaurant name, currency, "low stock"
threshold and the starting menu. The starting menu is only loaded the first
time, when the database is empty; after that, use the staff page.

## QR codes: please scan before printing

The QR generator is written from scratch for this project. It is tested against
published reference values (Reed-Solomon error-correction vector, format
information) and with a decoder that reads the generated codes back, but
**scan one with a phone before you print a full sheet**. The QR address must be
one the customers' phones can reach. `localhost` only works on the computer
running the server, so use your Wi-Fi address or your public `https://` address.

## Security

- Staff actions need a PIN; sessions use `HttpOnly`, `SameSite=Strict` cookies
- Login is rate-limited (5 wrong PINs, then a one-minute lockout)
- Changes also require a custom header and a same-origin request, which blocks cross-site forgery
- Strict Content-Security-Policy: no inline scripts or styles; menu text is shown with `textContent`, so it can't inject HTML
- Only the five public pages are served, never your source files or database
- Stock changes are atomic, so stock can't go negative if two orders land together
- Binds to `127.0.0.1` unless you pass `--host`

Over the internet, put it behind HTTPS (for example a Cloudflare Tunnel), because
the PIN is sent in clear text over plain HTTP.

## Known limits

- Customers view the menu but **can't order**. Staff enter sales by tapping "−1 sold".
- One shared staff PIN; no per-user accounts
- Refreshes by polling every 5 seconds, not push updates
- QR generator handles addresses up to 106 bytes

## Layout

| File | Role |
|---|---|
| `server.py` | HTTP server, staff login, API |
| `db.py` | SQLite storage, validation, stock logic |
| `qr.py` | QR code generator (SVG) |
| `static/` | customer menu and staff pages |
| `config.json` | name, currency and starting menu |

## Tests

```bash
python -m unittest -v
```

## License

MIT
