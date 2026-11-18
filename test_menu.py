import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import db as dbmod
import server
from db import MenuDB, clean_item

ITEM = {"category": "Mains", "name": "Fish Thali", "price_paise": 42000, "stock": 3, "veg": 0}


class DBTests(unittest.TestCase):
    def setUp(self):
        self.db = MenuDB(low_threshold=2)

    def test_create_and_status(self):
        it = self.db.create(ITEM)
        self.assertEqual(it["status"], "available")
        self.assertEqual(self.db.create({**ITEM, "name": "Unlimited", "stock": None})["stock"], None)

    def test_sold_one_counts_down_to_sold_out(self):
        it = self.db.create(ITEM)  # stock 3, low threshold 2
        self.assertEqual(self.db.sold_one(it["id"])["status"], "low")       # 2 left
        self.assertEqual(self.db.sold_one(it["id"])["stock"], 1)
        last = self.db.sold_one(it["id"])
        self.assertEqual(last["stock"], 0)
        self.assertEqual(last["status"], "sold_out")
        self.assertEqual(self.db.sold_one(it["id"]), "none_left")           # never negative
        self.assertEqual(self.db.get(it["id"])["stock"], 0)

    def test_unlimited_item_unaffected_by_sold(self):
        it = self.db.create({**ITEM, "stock": None})
        self.assertEqual(self.db.sold_one(it["id"])["stock"], None)

    def test_sold_missing_item(self):
        self.assertIsNone(self.db.sold_one(999))

    def test_manual_sold_out_switch(self):
        it = self.db.create(ITEM)
        self.assertEqual(self.db.update(it["id"], {"available": 0})["status"], "sold_out")
        self.assertEqual(self.db.update(it["id"], {"available": 1})["status"], "available")

    def test_version_bumps_on_change_only(self):
        v0 = self.db.version()
        it = self.db.create(ITEM)
        v1 = self.db.version()
        self.assertGreater(v1, v0)
        self.db.update(it["id"], {"stock": 10})
        self.assertGreater(self.db.version(), v1)
        v2 = self.db.version()
        self.db.get(it["id"])
        self.db.update(999, {"stock": 1})
        self.assertEqual(self.db.version(), v2)

    def test_partial_update_keeps_other_fields(self):
        it = self.db.create(ITEM)
        up = self.db.update(it["id"], {"price_paise": 50000})
        self.assertEqual(up["name"], "Fish Thali")
        self.assertEqual(up["stock"], 3)
        self.assertEqual(up["price_paise"], 50000)

    def test_update_stock_to_unlimited(self):
        it = self.db.create(ITEM)
        self.assertIsNone(self.db.update(it["id"], {"stock": None})["stock"])

    def test_delete(self):
        it = self.db.create(ITEM)
        self.assertTrue(self.db.delete(it["id"]))
        self.assertFalse(self.db.delete(it["id"]))

    def test_validation(self):
        for bad in ({**ITEM, "name": ""}, {**ITEM, "name": "x" * 81}, {**ITEM, "price_paise": -1},
                    {**ITEM, "price_paise": "abc"}, {**ITEM, "stock": -5}, {**ITEM, "stock": 10**6},
                    {**ITEM, "category": ""}):
            with self.assertRaises(ValueError, msg=str(bad)):
                clean_item(bad)

    def test_sql_injection_text_is_just_text(self):
        it = self.db.create({**ITEM, "name": "x'); DROP TABLE items;--"})
        self.assertEqual(self.db.get(it["id"])["name"], "x'); DROP TABLE items;--")
        self.assertEqual(self.db.count(), 1)


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.app = server.make_app(":memory:", pin="123456")
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(self.app))
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.cookie = None

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()

    def call(self, method, path, body=None, auth=False, headers=None):
        h = {"X-Staff": "1"} if method != "GET" else {}
        if body is not None:
            h["Content-Type"] = "application/json"
        if auth and self.cookie:
            h["Cookie"] = self.cookie
        h.update(headers or {})
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}",
                                     json.dumps(body).encode() if body is not None else None,
                                     h, method=method)
        try:
            r = urllib.request.urlopen(req)
        except urllib.error.HTTPError as e:
            r = e
        raw = r.read()
        return r.status, (json.loads(raw) if raw and r.headers.get("Content-Type", "").startswith("application/json") else raw), r

    def login(self, pin="123456"):
        code, _, r = self.call("POST", "/api/staff/login", {"pin": pin})
        if code == 200:
            self.cookie = r.headers["Set-Cookie"].split(";")[0]
        return code

    def test_public_menu_is_seeded_and_open(self):
        code, data, _ = self.call("GET", "/api/menu")
        self.assertEqual(code, 200)
        self.assertGreater(len(data["items"]), 3)
        self.assertEqual(data["name"], "Coastal Café")

    def test_menu_etag_304(self):
        _, _, r = self.call("GET", "/api/menu")
        etag = r.headers["ETag"]
        code, _, _ = self.call("GET", "/api/menu", headers={"If-None-Match": etag})
        self.assertEqual(code, 304)

    def test_pages_and_security_headers(self):
        for path in ("/", "/staff", "/style.css", "/menu.js", "/staff.js"):
            code, _, r = self.call("GET", path)
            self.assertEqual(code, 200, path)
            self.assertIn("default-src 'self'", r.headers["Content-Security-Policy"])
            self.assertEqual(r.headers["X-Content-Type-Options"], "nosniff")

    def test_no_inline_scripts_or_styles(self):
        for path in ("/", "/staff"):
            html = self.call("GET", path)[1].decode()
            self.assertNotIn("<style", html)
            self.assertNotIn(' style="', html)
            self.assertNotIn("onclick=", html)
            self.assertEqual(html.count("<script"), html.count("<script src="))

    def test_source_files_not_served(self):
        for path in ("/server.py", "/config.json", "/menu.db", "/../server.py", "/static/staff.js"):
            self.assertEqual(self.call("GET", path)[0], 404, path)

    def test_staff_endpoints_need_login(self):
        self.assertEqual(self.call("POST", "/api/staff/items", ITEM)[0], 401)
        self.assertEqual(self.call("PUT", "/api/staff/items/1", {"stock": 1})[0], 401)
        self.assertEqual(self.call("DELETE", "/api/staff/items/1")[0], 401)
        self.assertEqual(self.call("POST", "/api/staff/items/1/sold", {})[0], 401)
        self.assertEqual(self.call("GET", "/api/staff/qr.svg?data=hi")[0], 401)

    def test_wrong_pin_rejected_and_lockout(self):
        for _ in range(server.MAX_FAILS):
            self.assertEqual(self.login("000000"), 401)
        self.assertEqual(self.login("123456"), 429)  # right PIN is refused while locked out

    def test_session_cookie_flags(self):
        _, _, r = self.call("POST", "/api/staff/login", {"pin": "123456"})
        cookie = r.headers["Set-Cookie"]
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Strict", cookie)

    def test_csrf_header_required(self):
        self.login()
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/staff/items",
                                     json.dumps(ITEM).encode(),
                                     {"Cookie": self.cookie, "Content-Type": "application/json"},
                                     method="POST")
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(req)
        self.assertEqual(cm.exception.code, 403)

    def test_cross_origin_refused(self):
        self.login()
        code, _, _ = self.call("POST", "/api/staff/items", ITEM, auth=True,
                               headers={"Origin": "http://evil.example"})
        self.assertEqual(code, 403)

    def test_full_stock_flow_visible_to_customers(self):
        self.login()
        code, item, _ = self.call("POST", "/api/staff/items",
                                  {**ITEM, "name": "Test Dish", "stock": 2}, auth=True)
        self.assertEqual(code, 201)
        iid = item["id"]
        for expected in (1, 0):
            code, it, _ = self.call("POST", f"/api/staff/items/{iid}/sold", {}, auth=True)
            self.assertEqual((code, it["stock"]), (200, expected))
        self.assertEqual(self.call("POST", f"/api/staff/items/{iid}/sold", {}, auth=True)[0], 409)
        _, menu, _ = self.call("GET", "/api/menu")   # no login: what a customer sees
        dish = next(i for i in menu["items"] if i["id"] == iid)
        self.assertEqual(dish["status"], "sold_out")
        self.call("PUT", f"/api/staff/items/{iid}", {"stock": 10, "available": 1}, auth=True)
        _, menu, _ = self.call("GET", "/api/menu")
        self.assertEqual(next(i for i in menu["items"] if i["id"] == iid)["status"], "available")
        self.assertEqual(self.call("DELETE", f"/api/staff/items/{iid}", auth=True)[0], 200)

    def test_bad_input_gets_400(self):
        self.login()
        self.assertEqual(self.call("POST", "/api/staff/items", {**ITEM, "price_paise": -5}, auth=True)[0], 400)
        self.assertEqual(self.call("PUT", "/api/staff/items/1", {"stock": "lots"}, auth=True)[0], 400)

    def test_qr_endpoint(self):
        self.login()
        code, body, r = self.call("GET", "/api/staff/qr.svg?data=http%3A%2F%2F192.168.1.5%3A8000%2F%3Ft%3D1", auth=True)
        self.assertEqual(code, 200)
        self.assertEqual(r.headers["Content-Type"], "image/svg+xml")
        self.assertTrue(body.startswith(b"<svg"))
        self.assertEqual(self.call("GET", "/api/staff/qr.svg?data=" + "a" * 200, auth=True)[0], 400)

    def test_logout_invalidates_session(self):
        self.login()
        self.call("POST", "/api/staff/logout", {}, auth=True)
        self.assertEqual(self.call("POST", "/api/staff/items", ITEM, auth=True)[0], 401)


if __name__ == "__main__":
    unittest.main()
