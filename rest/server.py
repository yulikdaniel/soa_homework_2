import sqlite3
from flask import Flask, abort, request
import flask
from queue import Queue
import threading
from reportlab.pdfgen.canvas import Canvas
import random
import logging
import os

DB_NAME = "rest/profiles.db"
PORT = os.getenv("PORT", 15430)


def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS users (name TEXT PRIMARY KEY, age INTEGER, email TEXT, avatar_img TEXT, played INTEGER, wins INTEGER, ingame FLOAT)''')

    conn.commit()
    cursor.close()
    conn.close()


def add_entry(name, **columns):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(f"INSERT INTO users\
                   ({', '.join(['name'] + list(columns.keys()))}) SELECT ?{', ?' * len(columns)}\
                    WHERE NOT EXISTS (SELECT 1 FROM users WHERE name = ?)",\
                    [name] + list(columns.values()) + [name])
    conn.commit()
    cursor.close()
    conn.close()


def update_set_entry(name, **columns):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(f"UPDATE users SET\
                   { ', '.join([f'{column} = ?' for column in columns.keys()]) }\
                   WHERE name = ?", 
                    list(columns.values()) + [name])
    conn.commit()
    cursor.close()
    conn.close()


def update_add_entry(name, **columns):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(f"UPDATE users SET\
                   { ', '.join([f'{column} = {column} + ?' for column in columns.keys()]) }\
                   WHERE name = ?", 
                    list(columns.values()) + [name])
    conn.commit()
    cursor.close()
    conn.close()


def delete_entry(name):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM users WHERE name = ?", (name,))
    conn.commit()
    cursor.close()
    conn.close()


def lookup(name):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE name = ?", (name,))
    res = cursor.fetchone()
    conn.commit()
    cursor.close()
    conn.close()
    return res


queue = Queue()


def worker_pdf(queue_in):
    while True:
        task_id, name = queue_in.get()
        data = lookup(name)
        if data is None:
            canvas = Canvas(f"rest/reports/{task_id}.pdf", pagesize=(300, 50))
            canvas.drawString(12, 25, f"Profile with name {name} was not found...")
            canvas.save()
        else:
            canvas = Canvas(f"rest/reports/{task_id}.pdf", pagesize=(300, 110))
            canvas.drawString(12, 90, f"Name: {data[0]}")
            canvas.drawString(12, 75, f"Age: {data[1] if data[1] is not None else 'Not set'}")
            canvas.drawString(12, 60, f"Email: {data[2] if data[2] is not None else 'Not set'}")
            canvas.drawString(12, 45, f"Games played: {data[4] if data[4] is not None else 'Not set'}")
            canvas.drawString(12, 30, f"Wins: {data[5] if data[5] is not None else 'Not set'}")
            canvas.drawString(12, 15, f"Time spent playing: {round(data[6], 3) if data[6] is not None else 'Not set'} seconds")

            canvas.drawImage(f"rest/images/{data[3]}", x=200, y=10, width=90, height=90)
            canvas.save()

app = Flask(__name__)

@app.route("/users/<string:name>", methods=["POST"])
def add_user(name):
    logging.info(f"INSERT {name}")
    info = request.get_json()

    try:
        add_entry(name, avatar_img="default.png", played=0, wins=0, ingame=0, age=info.get("age"), email=info.get("email"))
    except:
        abort(400)

    return "Done\n"

@app.route("/users/<string:name>", methods=["PUT"])
def update_user(name):
    info = request.get_json()
    try:
        update_set_entry(name, age=info.get("age"), email=info.get("email"))
    except:
        abort(400)
    return "Done\n"

@app.route("/users/add/<string:name>", methods=["PUT"])
def update_user_add(name):
    info = request.get_json()
    try:
        update_add_entry(name, ingame=info.get("ingame"), played=info.get("played"), wins=info.get("wins"))
    except:
        abort(400)
    return "Done\n"

@app.route("/users/avatar/<string:name>", methods=["POST"])
def update_image(name):
    img = request.files.get("avatar")
    avatar = "default.png"
    if img is not None:
        img.save(f"rest/images/{name}.png")
        avatar = f"{name}.png"
    try:
        update_set_entry(name, avatar_img=avatar)
    except:
        abort(400)
    return "Done\n"

@app.route("/reports/<string:name>", methods=["POST"])
def post_task(name):
    id = random.randint(1000000, 9999999)
    queue.put((id, name))
    return f"It will be available by the link http://127.0.0.1:{PORT}/reports/{id}.pdf\n"


@app.route("/reports/<path:path>", methods=["GET"])
def give_report(path):
    return flask.send_from_directory("reports", path)


@app.route('/')
def home():
    return "You are home :3\n"


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    logging.info("Starting")
    init_db()
    worker_thread = threading.Thread(target=worker_pdf, args=[queue])
    worker_thread.start()
    app.run(host="0.0.0.0", port=PORT)
    worker_thread.join()