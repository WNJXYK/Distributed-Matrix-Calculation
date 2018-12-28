from flask import Flask, request, render_template, make_response, send_from_directory
from multiprocessing import Value, Manager
from multiprocessing.managers import BaseManager
import json, time, queue, math, os
import numpy
import h5py


class QueueManager(BaseManager): pass
class WorkerManager(BaseManager): pass
send_queue_instance, recv_queue_instance = queue.Queue(), queue.Queue()
QueueManager.register('Task_Queue', lambda: send_queue_instance)
QueueManager.register('Result_Queue', lambda: recv_queue_instance)

HDF5_PATH = os.path.split(os.path.realpath(__file__))[0] + "/static/data.hdf5"

app = Flask(__name__)

manager = Manager()
task = manager.dict()
task_running = Value('b', False)

#### Worker
worker_terminate = Value('b', False)
worker_running = Value('b', False)

def mul_worker(task):
	task["C"] = task["A"]*task["B"]
	task.pop("A") 
	task.pop("B")
	return task

def inv_worker(task):
	task["C"] = task["A"].I
	task.pop("A")
	return task

@app.route('/start_worker', methods = ['POST'])
def start_worker():
	# Only Allow One Worker Running
	if worker_running.value == True: return json.dumps({"status": 0, "message": "A Worker is Running"})

	# Start A Worker
	worker_terminate.value = False
	worker_running.value = True

	try:
		# Get Address
		host_ip = request.form.get('ip')
		host_port = int(request.form.get('port'))
		host_auth = str(request.form.get('auth')).encode(encoding='UTF-8',errors='strict')

		# Connect to Host
		server = WorkerManager(address = (host_ip, host_port), authkey = host_auth)
		server.connect()
		server.register('Task_Queue')
		server.register('Result_Queue')
		task_queue = server.Task_Queue()
		result_queue = server.Result_Queue()
		print("Worker Connect to %s:%d Auth=%s" % (host_ip, host_port, host_auth))


		# Running
		while True:
			# Terminate
			if worker_terminate.value == True: break

			# Work
			try:
				task = task_queue.get(timeout=1)
				time.sleep(0.00001)
				if task['type'] == 'Mul':  result_queue.put(mul_worker(task))
				if task['type'] == 'Inv':  result_queue.put(inv_worker(task))
				print("Worker : A %s Task" % task["type"])
			except queue.Empty:
				pass

			# Sleep
			time.sleep(0.00001)

	except Exception as e:
		print("Worker Error : %s" % str(e))
		return json.dumps({"status": 0, "message": "Worker Error : %s" % str(e)})
	finally:
		# Clear Flag
		worker_running.value = False
		worker_terminate.value = False

	return json.dumps({"status": 0, "message": "Worker Terminated"})

@app.route('/terminate_worker', methods = ['POST'])
def terminate_worker():
	# No Need
	if worker_running.value == False:
		worker_terminate.value = False
		return json.dumps({"status": 0, "message": "There is no Worker Running"})

	# Terminating
	if worker_terminate.value == True: return json.dumps({"status": 0, "message": "Terminating... Please Wait"})

	# Send An Signal
	worker_terminate.value = True
	return json.dumps({"status": 1, "message": "Terminating..."})

@app.route('/query_worker', methods = ['POST'])
def query_worker():
	if worker_running.value == False: return json.dumps({"status": 0, "message": "There is no Worker Running"})
	return json.dumps({"status": 1, "message": "A Worker is Running"})

##### Host
host_terminate = Value('b', False)
host_running = Value('b', False)

def block_divide(matrix, blk, blc):
	return [[numpy.matrix([[matrix[i*blk+ii, j*blk+jj] for jj in range(blk)] for ii in range(blk)]) for j in range(blc)] for i in range(blc)]

def block_merge(matrix, blk, blc):
	return numpy.matrix([[matrix[i][j][ii, jj] for j in range(blc) for jj in range(blk) ] for i in range(blc) for ii in range(blk) ])

def check_matrix(A, B):
	EPS = 1e-6
	A, B = numpy.array(A).flatten(), numpy.array(B).flatten()
	if len(A) != len(B): return False
	for i in range(len(A)):
		if math.fabs(A[i]-B[i])>EPS: return False
	return True

@app.route('/mul_task', methods = ['POST'])
def mul_task():
	if task_running.value == True : return json.dumps({"status": 0, "message": "A Task is Running"})
	if host_running.value == False: return json.dumps({"status": 0, "message": "There is no Host Running"})
	task_running.value = True

	global send_queue, recv_queue

	try:
		# Get Matrix Size & Block Size
		siz = int(request.form.get('size'))
		blk = int(request.form.get('block'))
		print("New Mul Task %d(%d)" % (siz, blk))

		# Calc Block Count
		if siz%blk !=0:
			task_running.value = False
			return json.dumps({"status": 0, "message": ("Make Sure Block_Size(%d) | Matrix_Size(%d)!"%(blk, siz))})
		blc = int(siz/blk)

		# Random Matrix
		A = numpy.matrix(numpy.random.rand(siz, siz))
		B = numpy.matrix(numpy.random.rand(siz, siz))
		C = numpy.matrix(numpy.zeros((siz, siz)))
		backupA = A
		backupB = B

		# Create Task
		task["type"] = 'Mul'
		task["A"] = A
		task["B"] = B
		task["status"] = 'Init'
		task["epoch"] = 0
		task["max_epoch"] = 1
		task["unit"] = 0
		task["max_unit"] = 0
		task["max_sunit"] = blc*blc*blc
		task["time"] = time.time()

		Ab = block_divide(A, blk, blc)
		Bb = block_divide(B, blk, blc)
		Cb = block_divide(C, blk, blc)
		for k in range(0, blc):
			for i in range(0, blc):
				for j in range(0, blc):
					task["max_unit"] = task["max_unit"] + 1
					send_queue.put({'type': 'Mul',
									'A': Ab[i][k],
									'B': Bb[k][j],
									'Info': (i, j)})

		# Recv Answer
		task["status"] = "Running"
		while task["unit"] < task["max_unit"]:
			try:
				res = recv_queue.get(timeout=1)
				info = res["Info"]
				Cb[info[0]][info[1]] += res["C"]
				task["unit"] = task["unit"] + 1
				print(
					"Recv Mul Task #%d/%d(%d/%d)" % (task["epoch"], task["max_epoch"], task["unit"], task["max_sunit"]))
			except queue.Empty:
				pass
			time.sleep(0.00001)
		task["epoch"] = task["epoch"]+1
	except Exception as e:
		print("Task Error : %s" % str(e))
	finally:
		# Clear Flag
		task["status"] = "Finished"
		task_running.value = False

	task["time"] = time.time() - task["time"]

	# Check
	if task["unit"] >= task["max_unit"] and task["epoch"] >= task["max_epoch"]:
		print("Check: Run")
		if (check_matrix(A*B, block_merge(Cb, blk, blc))):
			task["status"] = "Correct"
			print("Check: AC")

	# Save as File
	if os.path.exists(HDF5_PATH): os.remove(HDF5_PATH)
	file = h5py.File(HDF5_PATH)
	file.attrs['Task'] = "Multiply Task"
	file.create_dataset('A', data=backupA)
	file.create_dataset('B', data=backupB)
	file.create_dataset('Check', data=backupA*backupB)
	file.create_dataset('Ans', data=block_merge(Cb, blk, blc))
	file.close()
	task["status"] = task["status"] + "(Saved)"
	print("Saved")

	return json.dumps({"status": 1, "message": "Task Terminated"})

@app.route('/inv_task', methods = ['POST'])
def inv_task():
	if task_running.value == True : return json.dumps({"status": 0, "message": "A Task is Running"})
	if host_running.value == False: return json.dumps({"status": 0, "message": "There is no Host Running"})
	task_running.value = True

	global send_queue, recv_queue

	try:
		# Get Matrix Size & Block Size
		siz = int(request.form.get('size'))
		blk = int(request.form.get('block'))
		print("New Inv Task %d(%d)" % (siz, blk))

		# Calc Block Count
		if siz%blk !=0:
			task_running.value = False
			return json.dumps({"status": 0, "message": ("Make Sure Block_Size(%d) | Matrix_Size(%d)!"%(blk, siz))})
		blc = int(siz/blk)

		# Random Matrix
		A = numpy.matrix(numpy.random.rand(siz, siz))
		B = numpy.matrix(numpy.eye(siz, siz))
		backupA = A

		# Create Task
		task["type"] = 'Inv'
		task["A"] = A
		task["status"] = 'Init'
		task["epoch"] = 0
		task["max_epoch"] = blc
		task["unit"] = 0
		task["max_unit"] = 0
		task["max_sunit"] = 0
		task["time"] = time.time()

		A = block_divide(A, blk, blc)
		B = block_divide(B, blk, blc)

		task["status"] = "Running"
		lastA, lastB = A, B
		for k in range(blc):
			task["unit"] = task["max_unit"] = 0
			task["max_sunit"] = 1 + (blc-k-1) + k + (blc-k-1)*blc + k*blc + blc - blc
			A = [[numpy.matrix(numpy.eye(blk))] * blc for i in range(blc)]
			B = [[numpy.matrix(numpy.eye(blk))] * blc for i in range(blc)]

			# Step One
			# A[k][k] = lastA[k][k].I
			send_queue.put({'type': 'Inv',
							'A': lastA[k][k],
							'Info': (k, k)})
			task["max_unit"] = task["max_unit"] + 1
			while task["unit"] < task["max_unit"]:
				try:
					res = recv_queue.get(timeout=1)
					info = res["Info"]
					A[info[0]][info[1]] = res["C"]
					task["unit"] = task["unit"] + 1
					print("Recv Inv Task #%d/%d(%d/%d)" % (task["epoch"], task["max_epoch"], task["unit"], task["max_sunit"]))
				except queue.Empty:
					pass
				time.sleep(0.00001)
			B[k][k] = A[k][k]

			# Step Two
			for j in range(k + 1, blc):
				# A[k][j] = A[k][k] * lastA[k][j]
				send_queue.put({'type': 'Mul',
								'A': A[k][k],
								'B': lastA[k][j],
								'Info': (k, j, 'A')})
				task["max_unit"] = task["max_unit"] + 1
			for j in range(k):
				# B[k][j] = A[k][k] * lastB[k][j]
				send_queue.put({'type': 'Mul',
								'A': A[k][k],
								'B': lastB[k][j],
								'Info': (k, j, 'B')})
				task["max_unit"] = task["max_unit"] + 1
			while task["unit"] < task["max_unit"]:
				try:
					res = recv_queue.get(timeout=1)
					info = res["Info"]
					if info[2] == 'A':
						A[info[0]][info[1]] = res["C"]
					else:
						B[info[0]][info[1]] = res["C"]
					task["unit"] = task["unit"] + 1
					print("Recv Inv Task #%d/%d(%d/%d)" % (
					task["epoch"], task["max_epoch"], task["unit"], task["max_sunit"]))
				except queue.Empty:
					pass
				time.sleep(0.00001)

			# Step Three
			for j in range(k + 1, blc):
				for i in range(blc):
					if i == k: continue
					# A[i][j] = lastA[i][j] - lastA[i][k] * A[k][j]
					send_queue.put({'type': 'Mul',
									'A': lastA[i][k],
									'B': A[k][j],
									'Info': (i, j, 'A')})
					task["max_unit"] = task["max_unit"] + 1
			for j in range(k):
				for i in range(blc):
					if i == k: continue
					# B[i][j] = lastB[i][j] - lastA[i][k] * B[k][j]
					send_queue.put({'type': 'Mul',
									'A': lastA[i][k],
									'B': B[k][j],
									'Info': (i, j, 'B')})
					task["max_unit"] = task["max_unit"] + 1
			for i in range(blc):
				if i == k: continue
				# B[i][k] = -lastA[i][k] * A[k][k]
				send_queue.put({'type': 'Mul',
								'A': -lastA[i][k],
								'B': A[k][k],
								'Info': (i, k, 'Bs')})
				task["max_unit"] = task["max_unit"] + 1
			while task["unit"] < task["max_unit"]:
				try:
					res = recv_queue.get(timeout=1)
					info = res["Info"]
					if info[2] == 'A':
						A[info[0]][info[1]] = lastA[info[0]][info[1]] - res["C"]
					elif info[2] == 'B':
						B[info[0]][info[1]] = lastB[info[0]][info[1]] - res["C"]
					else:
						B[info[0]][info[1]] = res["C"]
					task["unit"] = task["unit"] + 1
					print("Recv Inv Task #%d/%d(%d/%d)" % (
					task["epoch"], task["max_epoch"], task["unit"], task["max_sunit"]))
				except queue.Empty:
					pass
				time.sleep(0.00001)

			lastA, lastB = A, B
			task["epoch"] = task["epoch"] + 1

	except Exception as e:
		print("Task Error : %s" % str(e))

	finally:
		# Clear Flag
		task["status"] = "Finished"
		task_running.value = False

	task["time"] = time.time() - task["time"]

	# Check
	if task["unit"] >= task["max_unit"] and task["epoch"] >= task["max_epoch"]:
		print("Check: Run")
		if (check_matrix(backupA.I, block_merge(B, blk, blc))):
			task["status"] = "Correct"
			print("Check: AC")

	# Save as File
	if os.path.exists(HDF5_PATH): os.remove(HDF5_PATH)
	file = h5py.File(HDF5_PATH)
	file.attrs['Task'] = "Multiply Task"
	file.create_dataset('A', data=backupA)
	file.create_dataset('Check', data=backupA.I)
	file.create_dataset('Ans', data=block_merge(B, blk, blc))
	file.close()
	task["status"] = task["status"] + "(Saved)"
	print("Saved")

	return json.dumps({"status": 1, "message": "Task Terminated"})

@app.route('/query_task', methods = ['POST'])
def query_task():
	return json.dumps({"type": task["type"],
					"status": task["status"],
					"epoch": task["epoch"],
					"max_epoch": task["max_epoch"],
					"unit": task["unit"],
					"max_unit": task["max_sunit"],
					"time": round(task["time"], 2)})

@app.route('/start_host', methods = ['POST'])
def start_host():
	# Only Allow One Host Running
	if host_running.value == True: return json.dumps({"status": 0, "message": "A Host is Running"})

	# Start A Host
	host_terminate.value = False
	host_running.value = True

	try:
		# Get Address
		host_ip = '0.0.0.0'
		host_port = int(request.form.get('port'))
		host_auth = str(request.form.get('auth')).encode(encoding='UTF-8',errors='strict')

		# Create A Host
		server = QueueManager(address = (host_ip, host_port), authkey = host_auth)
		server.start()
		global send_queue, recv_queue
		send_queue, recv_queue = server.Task_Queue(), server.Result_Queue()
		print("Host Running On %s:%d Auth=%s" % (host_ip, host_port, host_auth))

		# Running
		while True:
			# Terminate
			if host_terminate.value == True: break

			# Sleep
			time.sleep(0.1)

	except Exception as e:
		print("Host Error : %s" % str(e))
		return json.dumps({"status": 0, "message": "Host Error : %s" % str(e)})
	finally:
		# Clear Flag
		host_running.value = False
		host_terminate.value = False
		print("Host Terminated")
		server.shutdown()

	return json.dumps({"status": 0, "message": "Host Terminated"})

@app.route('/terminate_host', methods = ['POST'])
def terminate_host():
	# Task Running
	if task_running.value == True: return json.dumps({"status": 0, "message": "A Task is Running"})

	# No Need
	if host_running.value == False:
		host_terminate.value = False
		return json.dumps({"status": 0, "message": "There is no Host Running"})

	# Terminating
	if host_terminate.value == True: return json.dumps({"status": 0, "message": "Terminating... Please Wait"})

	# Send An Signal
	host_terminate.value = True
	return json.dumps({"status": 1, "message": "Terminating..."})

@app.route('/query_host', methods = ['POST'])
def query_host():
	if host_running.value == False: return json.dumps({"status": 0, "message": "There is no Host Running"})
	return json.dumps({"status": 1, "message": "A Host is Running"})

@app.route("/download", methods=['GET'])
def download():
	dirname = os.path.split(os.path.realpath(__file__))[0] + "/static"
	filename = "data.hdf5"
	response = make_response(send_from_directory(dirname, filename, as_attachment=True))
	response.headers["Content-Disposition"] = "attachment; filename={}".format(filename.encode().decode('latin-1'))
	return response

@app.route('/')
def index():
	return render_template('index.html')

if __name__ == '__main__':
	task["type"] = 'None'
	task["status"] = 'None'
	task["epoch"] = 0
	task["max_epoch"] = 0
	task["unit"] = 0
	task["max_unit"] = 0
	task["max_sunit"] = 0
	task["time"] = 0

	print(HDF5_PATH)
	app.run(
		host = '0.0.0.0',
		port = 80,
		debug = False,
		threaded = True
	)
