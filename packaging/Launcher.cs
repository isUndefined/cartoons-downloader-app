using System;
using System.Diagnostics;
using System.ComponentModel;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Text;
using System.Collections.Generic;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;

[assembly: AssemblyTitle("Cartoon Downloader")]
[assembly: AssemblyProduct("Cartoon Downloader Desktop")]
[assembly: AssemblyDescription("Portable Windows launcher with bundled Python and media tools")]
[assembly: AssemblyVersion("@@FILE_VERSION@@")]
[assembly: AssemblyFileVersion("@@FILE_VERSION@@")]

internal static class Launcher
{
    private sealed class ChildJob : IDisposable
    {
        [StructLayout(LayoutKind.Sequential)]
        private struct BasicLimits
        {
            public long ProcessTime, JobTime;
            public uint Flags;
            public UIntPtr MinimumWorkingSet, MaximumWorkingSet;
            public uint ActiveProcesses;
            public UIntPtr Affinity;
            public uint PriorityClass, SchedulingClass;
        }
        [StructLayout(LayoutKind.Sequential)]
        private struct IoCounters
        {
            public ulong ReadOperations, WriteOperations, OtherOperations;
            public ulong ReadBytes, WriteBytes, OtherBytes;
        }
        [StructLayout(LayoutKind.Sequential)]
        private struct ExtendedLimits
        {
            public BasicLimits Basic;
            public IoCounters Io;
            public UIntPtr ProcessMemory, JobMemory, PeakProcessMemory, PeakJobMemory;
        }
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        private static extern IntPtr CreateJobObject(IntPtr attributes, string name);
        [DllImport("kernel32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool SetInformationJobObject(IntPtr job, int kind, ref ExtendedLimits limits, uint size);
        [DllImport("kernel32.dll", SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);
        [DllImport("kernel32.dll")]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool CloseHandle(IntPtr handle);
        private IntPtr handle;

        public ChildJob()
        {
            handle = CreateJobObject(IntPtr.Zero, null);
            if (handle == IntPtr.Zero) throw new Win32Exception(Marshal.GetLastWin32Error());
            ExtendedLimits limits = new ExtendedLimits();
            limits.Basic.Flags = 0x2000; // JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE.
            if (!SetInformationJobObject(handle, 9, ref limits, (uint)Marshal.SizeOf(limits)))
            {
                int error = Marshal.GetLastWin32Error();
                Dispose();
                throw new Win32Exception(error);
            }
        }
        public void Attach(Process process)
        {
            if (!AssignProcessToJobObject(handle, process.Handle))
            {
                int error = Marshal.GetLastWin32Error();
                if (process.HasExited) return;
                process.Kill();
                process.WaitForExit();
                throw new Win32Exception(error, "Cannot protect the application's child process lifetime");
            }
        }
        public void Dispose()
        {
            if (handle != IntPtr.Zero) { CloseHandle(handle); handle = IntPtr.Zero; }
        }
    }

    // ProcessStartInfo on .NET Framework accepts a Windows command line. Quote
    // arguments using CommandLineToArgvW/CRT rules, including final backslashes.
    private static string Quote(string value)
    {
        StringBuilder result = new StringBuilder("\"");
        int slashes = 0;
        foreach (char character in value)
        {
            if (character == '\\') { slashes++; continue; }
            if (character == '"')
                result.Append('\\', slashes * 2 + 1);
            else
                result.Append('\\', slashes);
            result.Append(character);
            slashes = 0;
        }
        result.Append('\\', slashes * 2);
        return result.Append('"').ToString();
    }

    [STAThread]
    private static int Main(string[] arguments)
    {
        if (Array.IndexOf(arguments, "--diagnostics") >= 0) return Run(arguments);
        // Existence (not ownership) protects installation/uninstallation while
        // any app process is live. Setup must never force-stop an MTP transfer.
        using (var running = new System.Threading.Mutex(false, "Local\\CartoonDownloader.Desktop.Running"))
            return Run(arguments);
    }

    private static int Run(string[] arguments)
    {
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        bool quiet = Array.IndexOf(arguments, "--no-browser") >= 0;
        bool diagnostics = Array.IndexOf(arguments, "--diagnostics") >= 0;
        quiet = quiet || diagnostics;
        StringBuilder detail = new StringBuilder();
        object outputLock = new object();
        using (StreamWriter output = new StreamWriter(Console.OpenStandardOutput(), new UTF8Encoding(false)))
        using (StreamWriter errors = new StreamWriter(Console.OpenStandardError(), new UTF8Encoding(false)))
        {
            output.AutoFlush = true;
            errors.AutoFlush = true;
            Action<string, StreamWriter> write = delegate(string line, StreamWriter writer)
            {
                if (line == null) return;
                lock (outputLock)
                {
                    detail.AppendLine(line);
                    if (detail.Length > 16000) detail.Remove(0, detail.Length - 16000);
                    try { writer.WriteLine(line); }
                    catch (IOException) { } // A detached/closed parent pipe must not stop the application.
                }
            };
            try
            {
                string root = Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location);
                int attachIndex = Array.IndexOf(arguments, "--attach-url");
                if (attachIndex >= 0)
                {
                    int profileIndex = Array.IndexOf(arguments, "--ui-profile");
                    if (attachIndex + 1 >= arguments.Length || profileIndex < 0 || profileIndex + 1 >= arguments.Length)
                        throw new ArgumentException("The native window requires a local address and a profile folder.");
                    var configuration = new Dictionary<string, object> {
                        { "url", arguments[attachIndex + 1] }, { "profile", Path.GetFullPath(arguments[profileIndex + 1]) } };
                    DesktopWindow.ParseOrigin((string)configuration["url"]);
                    using (ChildJob windowJob = new ChildJob())
                    using (var window = new DesktopWindow(null, Task.FromResult(configuration), windowJob.Attach,
                        delegate(string line) { write(line, output); }))
                    {
                        Application.Run(window);
                        return window.Failed ? 1 : 0;
                    }
                }
                string python = Path.Combine(root, "runtime", "python", "python.exe");
                string script = Path.Combine(root, diagnostics ? "diagnostics.py" : "app.py");
                if (!File.Exists(python) || !File.Exists(script))
                    throw new FileNotFoundException("The application package is incomplete. Keep CartoonDownloader.exe with its runtime and resource folders.");
                // Ignore a system Python installation, PYTHONPATH and user site
                // packages. -B also avoids cache writes in installed resources.
                StringBuilder command = new StringBuilder("-E -s -B -u -X utf8 ");
                command.Append(Quote(script));
                if (!quiet) command.Append(" --no-browser --desktop-host");
                foreach (string argument in arguments)
                    if (argument != "--diagnostics") command.Append(' ').Append(Quote(argument));
                ProcessStartInfo start = new ProcessStartInfo(python, command.ToString());
                start.WorkingDirectory = root;
                start.UseShellExecute = false;
                start.CreateNoWindow = true;
                start.RedirectStandardOutput = true;
                start.RedirectStandardError = true;
                start.StandardOutputEncoding = Encoding.UTF8;
                start.StandardErrorEncoding = Encoding.UTF8;
                using (ChildJob job = new ChildJob())
                using (Process child = new Process())
                {
                    child.StartInfo = start;
                    var ready = new TaskCompletionSource<Dictionary<string, object>>();
                    child.OutputDataReceived += delegate(object sender, DataReceivedEventArgs eventArgs)
                    {
                        string line = eventArgs.Data;
                        write(line, output);
                        if (line != null && line.StartsWith("Desktop host: ", StringComparison.Ordinal))
                        {
                            try { ready.TrySetResult(new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(line.Substring(14))); }
                            catch (Exception error) { ready.TrySetException(error); }
                        }
                    };
                    child.ErrorDataReceived += delegate(object sender, DataReceivedEventArgs eventArgs) { write(eventArgs.Data, errors); };
                    child.Start();
                    job.Attach(child);
                    child.BeginOutputReadLine();
                    child.BeginErrorReadLine();
                    bool windowFailed = false;
                    if (!quiet)
                    {
                        using (var window = new DesktopWindow(child, ready.Task, job.Attach,
                            delegate(string line) { write(line, output); }))
                        {
                            Application.Run(window);
                            windowFailed = window.Failed;
                        }
                    }
                    // The parameterless wait also drains asynchronous output.
                    child.WaitForExit();
                    if (child.ExitCode != 0 && !quiet)
                        MessageBox.Show(detail.ToString(), "Cartoon Downloader", MessageBoxButtons.OK, MessageBoxIcon.Error);
                    return windowFailed ? 1 : child.ExitCode;
                }
            }
            catch (Exception error)
            {
                write(error.Message, errors);
                if (!quiet)
                    MessageBox.Show(error.Message, "Cartoon Downloader", MessageBoxButtons.OK, MessageBoxIcon.Error);
                return 1;
            }
        }
    }
}
