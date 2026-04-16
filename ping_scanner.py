"""
IP Subnet Ping Scanner - Windows GUI Tool
Scan all IPs in a CIDR subnet and display ping connectivity status.
"""

import ipaddress
import subprocess
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import socket
import csv
import time
import queue
from concurrent.futures import ThreadPoolExecutor, as_completed


def ping_host(ip, timeout=500):
    """Ping a single host, return (ip, is_alive, response_time_ms, hostname)."""
    try:
        # CREATE_NO_WINDOW = 0x08000000 - hide console window on Windows
        result = subprocess.run(
            ['ping', '-n', '1', '-w', str(timeout), ip],
            capture_output=True, text=True, timeout=3,
            creationflags=0x08000000
        )
        is_alive = result.returncode == 0
        response_time = None
        if is_alive:
            output = result.stdout
            for line in output.splitlines():
                if 'time' in line.lower() or 'ttl' in line.lower():
                    # Parse "time<1ms" or "time=12ms"
                    for part in line.split():
                        if 'time' in part.lower() or ('=' in part and part.endswith('ms')):
                            try:
                                t_str = part.split('=')[-1].replace('ms', '').strip()
                                response_time = float(t_str)
                            except (ValueError, IndexError):
                                response_time = None
                            break
        hostname = '-'
        if is_alive:
            try:
                hostname = socket.gethostbyaddr(ip)[0].split('.')[0]
            except socket.herror:
                pass
        return (ip, is_alive, response_time, hostname)
    except Exception:
        return (ip, False, None, '-')


class PingScannerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("IP Subnet Ping Scanner")
        self.root.geometry("850x600")
        self.root.minsize(750, 500)

        self.scanning = False
        self.cancel_flag = False
        self.results = []
        self.result_queue = queue.Queue()
        self.scan_start_time = 0
        self.total_count = 0
        self.done_count = 0
        self.online_count = 0
        self.offline_count = 0

        self._build_ui()

    def _build_ui(self):
        # --- Top frame: input + buttons ---
        top_frame = ttk.Frame(self.root, padding=10)
        top_frame.pack(fill=tk.X)

        ttk.Label(top_frame, text="CIDR:").pack(side=tk.LEFT, padx=(0, 5))
        self.cidr_var = tk.StringVar(value="192.168.1.0/24")
        self.cidr_entry = ttk.Entry(top_frame, textvariable=self.cidr_var, width=20)
        self.cidr_entry.pack(side=tk.LEFT, padx=(0, 10))

        self.scan_btn = ttk.Button(top_frame, text="扫描", command=self._start_scan)
        self.scan_btn.pack(side=tk.LEFT, padx=5)

        self.stop_btn = ttk.Button(top_frame, text="停止", command=self._stop_scan, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, padx=5)

        self.export_btn = ttk.Button(top_frame, text="导出CSV", command=self._export_csv, state=tk.DISABLED)
        self.export_btn.pack(side=tk.LEFT, padx=5)

        # --- Stats frame ---
        stats_frame = ttk.Frame(self.root, padding=(10, 0, 10, 5))
        stats_frame.pack(fill=tk.X)

        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(stats_frame, variable=self.progress_var, maximum=100)
        self.progress_bar.pack(fill=tk.X, pady=(0, 5))

        self.stats_var = tk.StringVar(value="就绪")
        ttk.Label(stats_frame, textvariable=self.stats_var, font=("", 9)).pack(fill=tk.X)

        # --- Treeview ---
        tree_frame = ttk.Frame(self.root, padding=10)
        tree_frame.pack(fill=tk.BOTH, expand=True)

        columns = ("ip", "status", "time", "hostname")
        self.tree = ttk.Treeview(tree_frame, columns=columns, show="headings", height=18)

        self.tree.heading("ip", text="IP 地址")
        self.tree.heading("status", text="状态")
        self.tree.heading("time", text="响应时间 (ms)")
        self.tree.heading("hostname", text="主机名")

        self.tree.column("ip", width=160, anchor=tk.W)
        self.tree.column("status", width=80, anchor=tk.CENTER)
        self.tree.column("time", width=120, anchor=tk.CENTER)
        self.tree.column("hostname", width=200, anchor=tk.W)

        scrollbar = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)

        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Configure tags for row colors
        self.tree.tag_configure("online", foreground="green")
        self.tree.tag_configure("offline", foreground="gray")

        # Status bar
        self.status_bar = ttk.Label(self.root, text="", relief=tk.SUNKEN, anchor=tk.W, padding=(5, 2))
        self.status_bar.pack(fill=tk.X, side=tk.BOTTOM)

    def _start_scan(self):
        cidr = self.cidr_var.get().strip()
        if not cidr:
            messagebox.showwarning("输入错误", "请输入 CIDR 网段，例如 192.168.1.0/24")
            return

        try:
            network = ipaddress.IPv4Network(cidr, strict=False)
        except ValueError:
            messagebox.showerror("输入错误", f"无效的 CIDR 格式: {cidr}")
            return

        # Exclude network and broadcast addresses for non-/32 subnets
        ips = [str(ip) for ip in network.hosts()] if network.prefixlen < 32 else [str(network.network_address)]

        self.total_count = len(ips)
        self.done_count = 0
        self.online_count = 0
        self.offline_count = 0
        self.results = []
        self.cancel_flag = False

        # Clear tree
        for item in self.tree.get_children():
            self.tree.delete(item)

        self.scan_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self.export_btn.config(state=tk.DISABLED)
        self.cidr_entry.config(state=tk.DISABLED)
        self.scanning = True

        self.scan_start_time = time.time()
        self._update_stats()

        import threading
        threading.Thread(target=self._scan_worker, args=(ips,), daemon=True).start()
        self._poll_results()

    def _scan_worker(self, ips):
        """Background thread: ping all IPs, push results to queue."""
        with ThreadPoolExecutor(max_workers=50) as executor:
            futures = {executor.submit(ping_host, ip): ip for ip in ips}
            for future in as_completed(futures):
                if self.cancel_flag:
                    executor.shutdown(wait=False, cancel_futures=True)
                    break
                try:
                    result = future.result()
                    self.result_queue.put(result)
                except Exception:
                    self.result_queue.put((futures[future], False, None, '-'))

    def _poll_results(self):
        """Main thread: poll queue and update UI."""
        try:
            while True:
                ip, is_alive, response_time, hostname = self.result_queue.get_nowait()
                self.results.append((ip, is_alive, response_time, hostname))
                self.done_count += 1
                if is_alive:
                    self.online_count += 1
                else:
                    self.offline_count += 1

                time_str = f"{response_time:.1f}" if response_time is not None else "-"
                tag = "online" if is_alive else "offline"
                status_text = "在线" if is_alive else "离线"
                self.tree.insert("", tk.END, values=(ip, status_text, time_str, hostname), tags=(tag,))

                self._update_stats()
        except queue.Empty:
            pass

        if self.done_count < self.total_count:
            self.root.after(100, self._poll_results)
        else:
            self._scan_complete()

    def _update_stats(self):
        elapsed = time.time() - self.scan_start_time
        pct = (self.done_count / self.total_count * 100) if self.total_count > 0 else 0
        self.progress_var.set(pct)
        self.stats_var.set(
            f"扫描进度: {self.done_count}/{self.total_count}  |  "
            f"在线: {self.online_count}  |  离线: {self.offline_count}  |  "
            f"耗时: {elapsed:.1f}s"
        )

    def _scan_complete(self):
        self.scanning = False
        self.scan_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)
        self.export_btn.config(state=tk.NORMAL)
        self.cidr_entry.config(state=tk.NORMAL)
        self.progress_var.set(100)
        self.status_bar.config(text=f"扫描完成 — 在线 {self.online_count} / 总计 {self.total_count}")

    def _stop_scan(self):
        self.cancel_flag = True
        self.stop_btn.config(state=tk.DISABLED)
        self.status_bar.config(text="正在停止扫描...")

    def _export_csv(self):
        if not self.results:
            messagebox.showinfo("导出", "没有可导出的结果")
            return

        filepath = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV 文件", "*.csv"), ("所有文件", "*.*")],
            initialfile=f"ping_scan_{time.strftime('%Y%m%d_%H%M%S')}.csv"
        )
        if not filepath:
            return

        try:
            with open(filepath, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.writer(f)
                writer.writerow(["IP 地址", "状态", "响应时间 (ms)", "主机名"])
                for ip, is_alive, response_time, hostname in self.results:
                    time_str = f"{response_time:.1f}" if response_time is not None else "-"
                    status_text = "在线" if is_alive else "离线"
                    writer.writerow([ip, status_text, time_str, hostname])
            self.status_bar.config(text=f"结果已导出至: {filepath}")
        except Exception as e:
            messagebox.showerror("导出失败", str(e))


def main():
    root = tk.Tk()
    app = PingScannerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
