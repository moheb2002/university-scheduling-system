from flask import Flask, request, jsonify, render_template, send_file
from flask_mysqldb import MySQL
from flask_cors import CORS
from dotenv import load_dotenv
import pandas as pd
from io import BytesIO
import os
import heapq
from itertools import combinations, groupby


load_dotenv()
app = Flask(__name__)
CORS(app)

app.config['MYSQL_HOST'] = os.getenv('MYSQL_HOST')
app.config['MYSQL_USER'] = os.getenv('MYSQL_USER')
app.config['MYSQL_PASSWORD'] = os.getenv('MYSQL_PASSWORD')
app.config['MYSQL_DB'] = os.getenv('MYSQL_DB')

mysql = MySQL(app)

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/add_room', methods=['POST'])
def add_room():
    data = request.json
    cursor = mysql.connection.cursor()
    cursor.execute("INSERT INTO rooms (room_name, capacity) VALUES (%s, %s)",
                    (data['room_name'], data['capacity']))
    mysql.connection.commit()
    cursor.close()
    return jsonify({'message': 'Room added successfully'})

@app.route('/add_lecture', methods=['POST'])
def add_lecture():
    data = request.json
    try:
        time = float(data['time']) 
        cursor = mysql.connection.cursor()
        cursor.execute("""INSERT INTO lectures (department, level, group_name, time, student_count, mode, day, subject_name)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""", 
                            (data['department'], data['level'], data['group_name'], time, data['student_count'],
                            data['mode'], data['day'], data['subject_name']))
        mysql.connection.commit()
        cursor.close()
        return jsonify({'message': 'Lecture added successfully'})
    except ValueError:
        return jsonify({'error': 'Invalid time format'}), 400


def get_rooms_from_db():
    cursor = mysql.connection.cursor()
    cursor.execute("SELECT room_name, capacity FROM rooms")
    rooms_data = cursor.fetchall()
    cursor.close()
    
    return {room[0]: {"capacity": room[1], "schedule": {}} for room in rooms_data}

def get_lectures_from_db():
    cursor = mysql.connection.cursor()
    cursor.execute("SELECT department, level, subject_name, group_name, student_count, mode, time, day FROM lectures")
    lectures = [
        {"department": d, "level": l, "subject_name": s, "group": g, "students": max(1, sc // 2), "mode": m, "time": t, "day": dy}
        for d, l, s, g, sc, m, t, dy in cursor.fetchall()
    ]
    cursor.close()
    return lectures

def assign_room(lecture, rooms):
    time, student_count, mode, day = lecture["time"], lecture["students"], lecture["mode"], lecture["day"]

    room_heap = [(details["capacity"], room, details) for room, details in rooms.items()]
    heapq.heapify(room_heap)

    if mode == "FTF":
        while room_heap:
            capacity, room, details = heapq.heappop(room_heap)
            if capacity >= student_count and time not in details["schedule"].get(day, []):
                details["schedule"].setdefault(day, {})[time] = f"{lecture['department']} {lecture['level']} {lecture['group']} ({lecture['subject_name']})"
                return [(room, time)]
        room_combos = find_multiple_rooms(student_count, list(rooms.items()), day, time)
        if room_combos:
            return [(room, time) for room, _ in room_combos]

    elif mode == "VCR":
        while room_heap:
            capacity, room, details = heapq.heappop(room_heap)
            if time not in details["schedule"].get(day, []):
                details["schedule"].setdefault(day, {})[time] = f"{lecture['department']} {lecture['level']} {lecture['group']} ({lecture['subject_name']})"
                return [(room, time)]

    return None  

def find_multiple_rooms(student_count, sorted_rooms, day, time):
    for r in range(2, len(sorted_rooms) + 1):  
        for room_combo in combinations(sorted_rooms, r):
            total_capacity = sum(details["capacity"] for room, details in room_combo)
            if total_capacity >= student_count and all(time not in details["schedule"].get(day, []) for _, details in room_combo):
                return room_combo
    return None

@app.route('/view_schedule')
def view_schedule():
    try:
        cursor = mysql.connection.cursor()
        cursor.execute("SELECT department, level, subject_name, group_name, time, mode, room_name, day FROM lecture_schedule")
        schedule_data = cursor.fetchall()
        cursor.close()
        return render_template('view_schedule.html', schedule_data=schedule_data)
    except Exception as e:
        return jsonify({'error': f'خطأ أثناء استرجاع الجدول: {str(e)}'}), 500

@app.route('/edit_lecture/<int:lecture_id>', methods=['GET', 'POST'])
def edit_lecture(lecture_id):
    cursor = mysql.connection.cursor()
    
    if request.method == 'GET':
        cursor.execute("SELECT * FROM lectures WHERE lecture_id = %s", (lecture_id,))
        lecture = cursor.fetchone()
        cursor.close()
        if lecture:
            return render_template('edit_lecture.html', lecture=lecture)
        else:
            return jsonify({'error': 'Lecture not found'}), 404
    
    if request.method == 'POST':
        data = request.form
        department = data['department']
        level = data['level']
        group_name = data['group_name']
        time = data['time']
        student_count = data['student_count']
        mode = data['mode']
        day = data['day']
        subject_name = data['subject_name']

        cursor.execute("""
            UPDATE lectures
            SET department = %s, level = %s, group_name = %s, time = %s,
                student_count = %s, mode = %s, day = %s, subject_name = %s
            WHERE lecture_id = %s
        """, (department, level, group_name, time, student_count, mode, day, subject_name, lecture_id))
        mysql.connection.commit()
        cursor.close()

        return jsonify({'message': 'Lecture updated successfully'})

@app.route('/delete_lecture/<int:lecture_id>', methods=['POST'])
def delete_lecture(lecture_id):
    cursor = mysql.connection.cursor()
    cursor.execute("SELECT * FROM lectures WHERE lecture_id = %s", (lecture_id,))
    lecture = cursor.fetchone()

    if not lecture:
        cursor.close()
        return jsonify({'error': 'Lecture not found'}), 404
    cursor.execute("DELETE FROM lectures WHERE lecture_id = %s", (lecture_id,))
    mysql.connection.commit()
    cursor.close()

    return jsonify({'message': 'Lecture deleted successfully'})


@app.route('/schedule_lectures', methods=['POST'])
def schedule_lectures():
    rooms = get_rooms_from_db()
    lectures = get_lectures_from_db()
    schedule_entries = []
    unassigned_lectures = []

    lectures.sort(key=lambda x: (x['day'], x['time']))
    grouped_lectures = {key: list(group) for key, group in groupby(lectures, key=lambda x: (x['day'], x['time']))}

    for (day, time), lecture_group in grouped_lectures.items():
        while lecture_group:
            for lecture in lecture_group[:]: 
                assigned_rooms = assign_room(lecture, rooms)
                if assigned_rooms:
                    for room, time in assigned_rooms:
                        schedule_entries.append((lecture['department'], lecture['level'], lecture['subject_name'], lecture['group'], time, lecture['mode'], room, lecture['day']))
                    lecture_group.remove(lecture)
                else:
                    unassigned_lectures.append(lecture)

    if schedule_entries:
        cursor = mysql.connection.cursor()
        cursor.executemany("""
            INSERT INTO lecture_schedule (department, level, subject_name, group_name, time, mode, room_name, day)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, schedule_entries)
        mysql.connection.commit()
        cursor.close()

    if unassigned_lectures:
        return jsonify({"error": f"بعض المحاضرات لم يتم جدولتها ({len(unassigned_lectures)})"}), 400

    return jsonify({"message": "تم جدولة المحاضرات بنجاح"})

@app.route('/clear_schedule', methods=['POST'])
def clear_schedule():
    cursor = mysql.connection.cursor()
    try:
        cursor.execute("DELETE FROM lecture_schedule")
        mysql.connection.commit()
        cursor.close()
        return jsonify({'message': 'تم مسح الجدول بنجاح'})
    except Exception as e:
        mysql.connection.rollback()
        cursor.close()
        return jsonify({'error': f'خطأ أثناء مسح الجدول: {str(e)}'}), 500

@app.route('/lectures', methods=['GET'])
def get_lectures():
    cursor = mysql.connection.cursor()
    cursor.execute("SELECT * FROM lectures")
    columns = [desc[0] for desc in cursor.description]
    lectures = []
    
    for row in cursor.fetchall():
        lecture = dict(zip(columns, row))
        lectures.append(lecture)
    
    cursor.close()
    return jsonify(lectures)

@app.route('/download_schedule')
def download_schedule():
    cursor = mysql.connection.cursor()
    cursor.execute("SELECT department, room_name,  level, subject_name, group_name, time, mode,day FROM lecture_schedule")
    schedule_data = cursor.fetchall()
    cursor.close()

    df = pd.DataFrame(schedule_data, columns=['Department', 'Room', 'Level', 'Subject', 'Group', 'Time', 'Mode', 'Day'])
    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        for room in df['Room'].unique():
            df[df['Room'] == room].to_excel(writer, index=False, sheet_name=room)

    output.seek(0)
    return send_file(output, as_attachment=True, download_name="lecture_schedule.xlsx",
                        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
if __name__ == '__main__':
    app.run(debug=True)