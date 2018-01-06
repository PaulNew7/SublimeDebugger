import bdb
import re
import traceback
import sys
import os
import inspect
from contextlib import contextmanager

def line(frame):
	return frame.f_lineno
def filename(frame):
	return os.path.realpath(frame.f_code.co_filename)
def function_name(frame):
	return frame.f_code.co_name or "<unknown>"
def match_range(s):
	nm=re.match("(\d+)$",s)
	if nm:
		nm = int(nm.groups()[0])
		return nm,nm+1,1
	m = re.match("(\d*)(?::(\d*)(?::(\d+))?)?$",s)
	if m:
		start,end,step = [(int(n) if n else None) for n in m.groups()]
		start,end,step = start or 0, end, step or 1
		return start,end,step
	return False
def n_in_range(n,ran):
	start,end,step = ran
	return start <= n and ((not end) or n<end) and (n-start)%step == 0

class MyDB(bdb.Bdb):

	breakpoints = {}
	def user_call(self, frame, args):
		"""This method is called when there is the remote possibility
		that we ever need to stop in this function."""
		if self._wait_for_mainpyfile:
			return		
		print("--call--",function_name(frame), args)
		self.stack, self.curidx = self.get_stack(frame, None)
		if self.stop_here(frame):
			self.wait_cmd(frame)

	def user_line(self, frame):
		if self._wait_for_mainpyfile:
			if (self.mainpyfile != filename(frame) or frame.f_lineno<= 0):
				return
			self._wait_for_mainpyfile = False
		print ("--line--")
		print( "break at", filename(frame), line(frame), "in", function_name(frame))
		self.stack, self.curidx = self.get_stack(frame, None)
		self.wait_cmd(frame) # continue to next breakpoint

	def user_return(self, frame, value):
		if self._wait_for_mainpyfile:
			return		
		print ("--return--")
		print ("return from", function_name(frame), value)
		self.stack, self.curidx = self.get_stack(frame, None)
		self.wait_cmd(frame) # continue

	def user_exception(self, frame, exception):
		if self._wait_for_mainpyfile:
			return		
		print("--exception--")
		print("exception in", function_name(frame), exception)
		self.stack, self.curidx = self.get_stack(frame, exception[2])
		self.wait_cmd(frame) # continue

	def wait_cmd(self,frame):
		self.curframe = frame
		ls={k:repr(v) for k,v in self.filter_vars(frame.f_locals).items()}
		gs={k:repr(v) for k,v in self.filter_vars(frame.f_globals).items()}
		import __main__
		self.main_debug = __main__.__dict__.copy()
		with self.exit__main__(self.main_copy):
			cmd = self.parent.E_get_cmd(line(frame),ls,gs, filename(frame)).decode()
		cmd = cmd or (self.last_cmd if hasattr(self, 'last_cmd') else '')
		self.last_cmd = cmd
		cmdl = (cmd.split() or [''])
		s,args = cmdl[0], cmdl[1:]
		if   s in ['c']: self.set_continue()
		elif s in ['n']: self.set_next(frame)
		elif s in ['b']:
			f, l = self.mainpyfile, int(args[0])
			if len(args)>1:
				mr = match_range(args[1])
				if args[1] == "c":
					self.parent.E_clear_break(f,l)
					self       .clear_break(f,l)
				elif mr:
					self.parent.E_clear_break(f,l)
					self       .clear_break(f,l)
					self.parent.E_set_break(f,l,{"range": mr, "hits" : 0})
					self       .set_break(f,l,{"range": mr, "hits" : 0})
				else :
					self.parent.E_clear_break(f,l)
					self       .clear_break(f,l)
					self.parent.E_set_break(f,l,{"cond":args[1]})
					self       .set_break(f,l,{"cond":args[1]})
			else:
				self.parent.E_clear_break(f,l)
				self       .clear_break(f,l)
				self.parent.E_set_break(f,l,{})
				self       .set_break(f,l,{})
			# self.parent.E_toggle_break(f,l)
			# self.toggle_break(f,l)
			self.wait_cmd(frame)
		elif s in ['s']: self.set_step()
		elif s in ['q']: self.set_quit()
		elif s in ['r']: self.set_return(frame)
		elif s in ['u']: self.set_until(frame, int(args[0]) if args else None)
		elif s in ['o']:
			self.curidx = self.curidx-1
			self.wait_cmd(self.stack[self.curidx][0])
		elif s in ['i']:
			self.curidx = self.curidx+1
			self.wait_cmd(self.stack[self.curidx][0])
		elif s in ['h']:
			self.show_help()
			self.wait_cmd(frame)
		else           : self.wait_cmd(frame)
	def show_help(self):
		self.parent.E_show_help("""
			Commands               Description
			c                      Continue execution, only stop when a breakpoint is encountered.
			n                      Continue execution until the next line in the current function is reached or
			                       it returns.
			b LINE[ COND|RANGE|c]  Set break at LINE in the current file. If a COND expression is supplied, the
			                       debugger stops at LINE only when COND evaluates to True. If a RANGE 
			                       expression (a expression matching the syntax of Python slices) is supplied,
			                       the debugger stops at LINE only when the hit count of the breakpoint is one
			                       of the numbers generated by RANGE. If letter c appears after LINE, the
			                       breakpoint is cleared.
			s                      Execute the current line, stop at the first possible occasion (either in a
			                       function that is called or in the current function).
			q                      Quit the debugger.
			r                      Continue execution until the current function returns.
			u [LINE]               Without argument, continue execution until the line with a number greater
			                       than the current one is reached.  With a line number, continue execution
			                       until a line with a number greater or equal than LINE is reached. In both
			                       cases, also stop when the current frame returns.
			o                      Move the current frame one level up in the stack trace (to an older frame).
			i                      Move the current frame one level down in the stack trace (to a newer frame).
			h                      Show this help.

			If no command is given, the previous command is repeated.
			""")
	def runscript(self,filename):
		# The script has to run in __main__ namespace (or imports from
		# __main__ will break).
		#
		# So we clear up the __main__ and set several special variables
		# (this gets rid of pdb's globals and cleans old variables on restarts).
		import __main__
		__main__.__dict__
		self.main_copy = __main__.__dict__.copy()
		self.main_debug= {	"__name__"    : "__main__",
							"__file__"    : filename,
							"__builtins__": __builtins__,
						}
		__main__.__dict__.clear()
		__main__.__dict__.update(self.main_debug)
		# When bdb sets tracing, a number of call and line events happens
		# BEFORE debugger even reaches user's code (and the exact sequence of
		# events depends on python version). So we take special measures to
		# avoid stopping before we reach the main script (see user_line and
		# user_call for details).
		self.mainpyfile = os.path.realpath(filename)
		self._user_requested_quit = False
		with open(filename, "rb") as fp:
			statement = "exec(compile(%r, %r, 'exec'))" % \
						(fp.read(), self.mainpyfile)
		self.clear_all_breaks()
		for filenam,lines in self.breakpoints.items():
			for l,bpinfo in lines.items():
				self.set_break(filenam, l,bpinfo)
		# Replace pdb's dir with script's dir in front of module search path.
		sys.path[0] = os.path.dirname(self.mainpyfile)
		try :
			self._wait_for_mainpyfile = True
			self.run(statement)
		except SyntaxError:
			print ("SyntaxError")
			traceback.print_exc()
			self.parent.E_show_exception("syntax error")
		except:
			traceback.print_exc()
			print ("Uncaught exception. Entering post mortem debugging")
			typ, val, t = sys.exc_info()
			self.parent.E_show_exception(str(val))
			self.stack, self.curidx = self.get_stack(None, t)
			self.wait_cmd(self.stack[self.curidx][0])			
		for filenam,lines in self.breakpoints.items():
			for l,bpinfo in lines.items():
				if "hits" in bpinfo:
					bpinfo["hits"]=0
		self.parent.E_finished()
		__main__.__dict__.clear()
		__main__.__dict__.update(self.main_copy)
	@contextmanager
	def exit__main__(self, main_dict):
		import __main__
		cur_dict = __main__.__dict__.copy()
		__main__.__dict__.clear()
		__main__.__dict__.update(main_dict)
		try:
			yield
		except Exception as e:
			raise e
		finally: 
			__main__.__dict__.clear()
			__main__.__dict__.update(cur_dict)
	def tryeval(self,expr):
		try:
			with self.exit__main__(self.main_debug):  
				ret = repr(eval(expr, self.curframe.f_globals, self.curframe.f_locals))
			return ret
		except Exception as e:
			return e
	def toggle_break(self,filename,line):
		if not filename in self.breakpoints: self.breakpoints.update({filename:{}})
		bps = self.breakpoints[filename]
		bps.pop(line)   if line in bps else bps.update({line:{}})
		(self.set_break if line in bps else self.clear_break)(filename, line)
	def break_here(self,frame):
		if not bdb.Bdb.break_here(self,frame): return False
		f, l = filename(frame), line(frame)
		bp = self.breakpoints[f][l]
		if not "range" in bp: return True
		bp["hits"] += 1
		return n_in_range(bp["hits"]-1,bp['range'])
	def set_break(self,filename,line,bpinfo={},**kwargs):
		bdb.Bdb.set_break(self,filename,line,**(bpinfo if "cond" in bpinfo else {}))
		if not filename in self.breakpoints: self.breakpoints.update({filename:{}})
		bps = self.breakpoints[filename]
		if not line in bps: bps.update({line:{}})
		bps[line]=bpinfo
	def clear_break(self,filename,line):
		bdb.Bdb.clear_break(self,filename,line)
		if not filename in self.breakpoints: self.breakpoints.update({filename:{}})
		bps = self.breakpoints[filename]
		if line in bps: bps.pop(line)
	def filter_vars(self, d):
		# try:
		# 	d.pop("__builtins__") # this messes up things (not eval defined): copy d first
		# except:
		# 	pass
		return d