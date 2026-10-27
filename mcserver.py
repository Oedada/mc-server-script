#!/usr/bin/env python3
import subprocess
import argparse
from pathlib import Path
import json
from collections import deque, defaultdict
import time
import os
import re
    
class Config():

    def __init__(self, path: Path | str):
        with open(path, "r") as f:
            self.servers = defaultdict(self.factory, json.load(f))
    
    def __getitem__(self, key: str):
        if self.servers[key] == "Not defined":
            raise KeyError("Server not defined")
        else:
            return Server(**self.servers[key])

    def list(self):
        return self.servers

    def factory(self):
        return "Not defined"

def run_command(cmd: list, path: str):
    return subprocess.run(
        cmd, # команда и аргументы
        capture_output=True, # перехват stdout и stderr
        text=True, # декодировать в строки (иначе bytes)
        check=False, # бросает исключение при коде != 0
        cwd=path, # рабочая директория
        env=os.environ.copy(),# окружение
        shell=False # запуск через shell
    )

def check_time(start, max_time) -> bool:
        return time.time() - start > max_time

class Server():

    def __init__(self, root_path: str | Path, session_name: str, core_file_name: str = "core.jar", log_file_relative_path: str = "logs/latest.log", verbose: bool = False, test_mode: bool = False, java_args: list = ["-Xmx8G", "-Xms2G", "-jar"]):
        self.test_mode = test_mode
        self.START_DONE_PATTERN = r"Done \([\d.]+s\)!"
        self.STOP_DONE_PATTERN = r"All RegionFile I/O tasks to complete"
        self.past_line = ""
        self.last_line = ""
        if isinstance(root_path, str):
            root_path = Path(root_path)
        self.session_name = session_name
        self.root_path = root_path
        self.jar_file = root_path / core_file_name
        self.log_file = root_path / log_file_relative_path
        self.verbose = verbose
        self.java_args = java_args
    
    def _read_log(self):
        self.past_line = self.last_line
        try:
            with open(self.log_file, "r") as f:
                self.last_line = deque(f, maxlen=1)
                if len(self.last_line) != 0:
                    self.last_line = self.last_line[0]
                else:
                    self.last_line = ""
        except FileNotFoundError:
                self.last_line = ""

    def _check_log(self, true_phrase: str):
            self._read_log()
            if self.verbose:
                if self.last_line != self.past_line:
                    print(self.last_line, end="")
            if re.search(true_phrase, self.last_line) is not None:
                return True
            return False
            
    def start(self, start_zerotier: bool = True, max_wait_time: int = 120):
        self.clear()
        if not self.test_mode:
            done_signal = f"mc_server_{self.session_name}_done"
            # create session
            run_command(["tmux", "new-session", "-d", "-s", self.session_name], self.root_path)
            #open zerotier connect
            if start_zerotier:
                run_command(["systemctl", "start", "zerotier-one.service"], self.root_path)
            # run server
            run_command(["tmux", "send-keys", "-t", self.session_name, "-l", f"java {" ".join(self.java_args)} {self.jar_file} nogui; tmux wait-for -S {done_signal}\n"], self.root_path)

            start_time = time.time()
            proc = subprocess.Popen(["tmux", "wait-for", done_signal], stdout=subprocess.PIPE, text=True)
            while True:
                if check_time(start_time, max_wait_time):
                    break
                if self._check_log(self.START_DONE_PATTERN):
                    print("Server started successfully")
                    break
                if proc.poll() is not None:
                    print("The server crashed")
                    break
        else:
            print("Server started successfull")
        
    def stop(self, stop_zerotier: bool = True, max_wait_time: int = 120):
        if not self.test_mode:
            if stop_zerotier:
                run_command(["systemctl", "stop", "zerotier-one.service"], self.root_path)
            # run server
            run_command(["tmux", "send-keys", "-t", self.session_name, "-l", "stop\n"], self.root_path)
            start_time = time.time()
            while True:
                if check_time(start_time, max_wait_time):
                    break
                if self._check_log(self.STOP_DONE_PATTERN):
                    print("Server stopped succesfully")
                    break
            run_command(["tmux", "kill-session", "-t", self.session_name], self.root_path)
        else:
            print("Server stopped succesfully")

    def clear(self):
        if not self.test_mode:
            run_command(["systemctl", "stop", "zerotier-one.service"], self.root_path)
            run_command(["tmux", "kill-session", "-t", self.session_name], self.root_path)
        else:
            print("Server stopped succesfully")

    def open_console(self):
        os.execvp("tmux", ["tmux",  "attach",  "-t", self.session_name])
        
    def restart(self):
        self.stop()
        self.start()

parser = argparse.ArgumentParser(description="Utility for manage your minecraft servers")
sub = parser.add_subparsers(dest="command", required=True)

def add_cmd(p):
    p.add_argument("server_name", help="Server name in the config")
    p.add_argument("-v", "--verbose", action="store_true", default=False)

subparsers = {}
for name in ["start", "stop", "clear", "restart", "open"]:
    subparsers[name] = sub.add_parser(name)
    add_cmd(subparsers[name])
sub.add_parser("list")
args = parser.parse_args()

cfg = Config("./mcs.json")

if args.command == "list":
    for server in cfg.list():
        print(server)
else:
    server = cfg[args.server_name]
    server.verbose = args.verbose
    if args.command == "start":
        server.start()
    if args.command == "stop":
        server.stop()
    if args.command == "clear":
        server.clear()
    if args.command == "restart":
        server.restart()
    if args.command == "open":
        server.open_console()
    
