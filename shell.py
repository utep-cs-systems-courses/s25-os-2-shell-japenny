#! /usr/bin/env python3

import os, sys, re

class Shell:
    def __init__(self):
        self.std_cmds = {
            "cd": self.cd,
            "exit": self.exit,
            "pwd": self.pwd,
        }

    def parser(self, cmds):
        pipe_commands = cmds.split('|')
        commands = []
        n_cmds, i = len(pipe_commands), 0

        while i < n_cmds:
            cmd = pipe_commands[i]
            cmd = cmd.strip()

            # Background process
            background = False
            if cmd.endswith('&'):
                if i < n_cmds - 1:
                    os.write(2, "-bash: syntax error near unexpected token `|'\n".encode())
                    return False
                else:
                    background = True
                    cmd = cmd[:-1].strip()

            # Use regex to find input and output redirections
            inp_match = re.search(r'<\s*(\S+)', cmd)
            out_match = re.search(r'>\s*(\S+)', cmd)

            inp = inp_match.group(1) if inp_match else None
            out = out_match.group(1) if out_match else None

            # Remove redirection parts from the command
            cmd = re.sub(r'[<>]\s*\S+', '', cmd).strip()

            # Split command and arguments
            parts = cmd.split()
            if parts:
                commands.append({
                    'cmd': parts[0],
                    'args': parts,
                    'input': inp,
                    'output': out,
                    'background': background
                })
            i+=1
        return commands

    def pwd(self, args):
        os.write(1, os.getcwd().encode())

    def cd(self, args):
        try:
            if len(args) == 1:
                os.chdir(os.path.expanduser('~'))
            elif args[1] == '~':
                os.chdir(os.path.expanduser('~'))
            elif args[1] == '/':
                os.chdir('/')
            else:
                os.chdir(args[1])
        except FileNotFoundError:
            print(f"cd {args[1]}: No such file or directory")
        except PermissionError:
            print(f"cd {args[1]}: Permission denied")

    def exit(self, args):
        sys.exit(0)

    def find_executable(self, cmd):
        # print(cmd, flush=True)
        cmd = cmd['cmd']
        if os.path.isabs(cmd) and os.access(cmd, os.X_OK):
            return cmd

        # Search for executable
        paths = re.split(":", os.environ['PATH'])
        for path in paths:
            exe = os.path.join(path, cmd)
            # os.write(1, f"Checking exe {exe}\n".encode())
            if os.access(exe, os.X_OK):
                return exe

        return None

    def execute(self, exe, cmd):
        if exe is None:
            # os.write(2, f"Child: Could not execute {exe}\n".encode())
            os.write(2, f"{cmd['cmd']}: command not found\n".encode())
            sys.exit(1)

        # Attempt to run executable
        try:
            os.execve(exe, cmd['args'], os.environ)
        except FileNotFoundError:
            os.write(2, f"Failed to execute: {exe}".encode())
            sys.exit(1)

    def redirect(self, cmd):
        if cmd['input']:
            os.close(0)
            os.open(cmd['input'], os.O_RDONLY)
            os.set_inheritable(0, True)

        if cmd['output']:
            os.close(1)
            os.open(cmd['output'], os.O_CREAT | os.O_WRONLY)
            os.set_inheritable(1, True)

    def run_cmds(self, cmds):
        cmd_0, cmd_1 = cmds if len(cmds) != 1 else (cmds[0], None)
        is_background = cmds[-1].get('background')

        pr, pw = None, None
        if cmd_1:
            pr, pw = os.pipe()
            for f in (pr, pw):
                os.set_inheritable(f, True)
            # print("pipe fds: pr=%d, pw=%d" % (pr, pw))

        pid = os.getpid()
        # os.write(2, f"About to fork pid{pid}".encode())
        rc = os.fork()

        if rc < 0:
            os.write(2, ("Fork failed, returning %d\n" % rc).encode())
            sys.exit(1)

        elif rc == 0:  # If child
            # os.write(2, f"Child: My pid={os.getpid()}. Parent's pid={pid}".encode())
            exe = self.find_executable(cmd_0)
            self.redirect(cmd_0)

            # Pipe output
            if cmd_1:
                os.close(pr) # Close unused read end
                os.dup2(pw, 1) # Redirect stdout to write end of pipe
                os.close(pw) # Close original write end

            # os.write(2, f"Child: Attempting to execute {exe}\n".encode())
            self.execute(exe, cmd_0)

        else: # parent
            if cmd_1:
                os.close(pw)  # Close unused write end
                child1_status = os.waitpid(rc, 0)

                if child1_status[1] != 0:
                    os.write(2,
                             f"Parent: Child 1 {child1_status[0]} "
                             f"terminated with exit code {child1_status[1]}\n".encode())
                rc2 = os.fork()

                if rc2 < 0:
                    os.write(2, ("Second fork failed, returning %d\n" % rc).encode())
                    sys.exit(1)
                elif rc2 == 0:
                    exe2 = self.find_executable(cmd_1)
                    self.redirect(cmd_1)

                    os.dup2(pr, 0)  # Redirect std input to the read end of the pipe
                    os.close(pr)  # Close original read end

                    # os.write(2, f"Second child: Attempting to execute {exe2}\n".encode())
                    self.execute(exe2, cmd_1)
                else:
                    os.close(pr)

                    if is_background:
                        os.write(2, f"Background process (pipe)\n".encode())
                        return

                    child2_status = os.waitpid(rc2, 0)
                    if child2_status[1] != 0:
                        os.write(1,
                                 f"Parent: Child 2 {child2_status[0]} "
                                 f"terminated with exit code {child2_status[1]}\n".encode())

            else:
                if is_background:
                    os.write(2, f"Background process (single)\n".encode())
                    return
                # os.write(2, f"Parent: My pid:{pid}, Child pid:{rc}\n".encode())
                childPidCode = os.wait()
                if childPidCode[1] != 0:
                    os.write(1, f"Parent: Child {childPidCode[0]} terminated "
                                    f"with exit code {childPidCode[1]}\n".encode())

    def run_shell(self):
        ps1 = os.getenv("PS1", "$ ")

        while True:
            try:
                os.write(1, ps1.encode())
                user_in = sys.stdin.readline().strip()

                if user_in.startswith("exit"):
                    self.exit('')

                if len(user_in) == 0:
                    print("")
                    continue

                # Parse commands and run
                parsed_cmds = self.parser(user_in)
                if not parsed_cmds:
                    print("no commands")
                    continue

                self.run_cmds(parsed_cmds)

            # Exit program
            except EOFError:
                print("\nEOFError. Exiting shell.")
                break

            except SystemExit:
                print("Exiting shell.")
                break

if __name__ == '__main__':
    shell = Shell()
    shell.run_shell()