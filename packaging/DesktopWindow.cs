using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Net;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

// The host only displays this application's loopback origin. It exposes no
// filesystem/host objects to page scripts and shares no personal browser profile.
internal sealed class DesktopWindow : Form
{
    private readonly Process server;
    private readonly Task<Dictionary<string, object>> ready;
    private readonly Action<Process> attachBrowser;
    private readonly Action<string> output;
    private readonly WebView2 view = new WebView2();
    private readonly Label status = new Label();
    private readonly Timer lifetime = new Timer();
    private Uri origin;
    private bool closing;
    private bool allowClose;
    private bool failed;
    private bool checkingServer;
    private bool lightTheme;

    [DllImport("dwmapi.dll")]
    private static extern int DwmSetWindowAttribute(IntPtr window, int attribute, ref int value, int size);

    private void ApplyWindowTheme(bool light)
    {
        lightTheme = light;
        Color background = light ? Color.FromArgb(238, 243, 248) : Color.FromArgb(6, 17, 27);
        Color foreground = light ? Color.FromArgb(20, 37, 54) : Color.FromArgb(245, 248, 251);
        Color border = light ? Color.FromArgb(215, 224, 232) : Color.FromArgb(32, 50, 65);
        BackColor = background;
        view.DefaultBackgroundColor = background;
        status.ForeColor = foreground;
        if (!IsHandleCreated) return;
        int dark = light ? 0 : 1;
        // Unsupported DWM attributes return HRESULTs on older Windows versions;
        // keep the native frame and its normal resize/snap/caption buttons.
        if (DwmSetWindowAttribute(Handle, 20, ref dark, sizeof(int)) < 0)
            DwmSetWindowAttribute(Handle, 19, ref dark, sizeof(int));
        int captionColor = ColorTranslator.ToWin32(background);
        int textColor = ColorTranslator.ToWin32(foreground);
        int borderColor = ColorTranslator.ToWin32(border);
        DwmSetWindowAttribute(Handle, 35, ref captionColor, sizeof(int));
        DwmSetWindowAttribute(Handle, 36, ref textColor, sizeof(int));
        DwmSetWindowAttribute(Handle, 34, ref borderColor, sizeof(int));
    }

    protected override void OnHandleCreated(EventArgs args)
    {
        base.OnHandleCreated(args);
        ApplyWindowTheme(lightTheme);
    }

    internal bool Failed { get { return failed; } }

    internal DesktopWindow(Process server, Task<Dictionary<string, object>> ready,
                           Action<Process> attachBrowser, Action<string> output)
    {
        this.server = server;
        this.ready = ready;
        this.attachBrowser = attachBrowser;
        this.output = output;
        Text = "Cartoon Downloader";
        Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath);
        StartPosition = FormStartPosition.CenterScreen;
        Size available = Screen.PrimaryScreen.WorkingArea.Size;
        Size = new Size(Math.Min(1680, available.Width - 40), Math.Min(920, available.Height - 40));
        MinimumSize = new Size(800, 560);
        BackColor = Color.FromArgb(9, 17, 23);
        view.Dock = DockStyle.Fill;
        view.DefaultBackgroundColor = BackColor;
        status.Dock = DockStyle.Fill;
        status.TextAlign = ContentAlignment.MiddleCenter;
        status.ForeColor = Color.White;
        status.Font = new Font("Segoe UI", 12);
        status.Text = "Starting Cartoon Downloader...";
        Controls.Add(view);
        Controls.Add(status);
        Shown += Initialize;
        FormClosing += CloseApplication;
        lifetime.Interval = 250;
        lifetime.Tick += async delegate
        {
            if (server != null && server.HasExited)
            {
                allowClose = true;
                Close();
            }
            else if (server == null && origin != null && !checkingServer && !closing)
            {
                checkingServer = true;
                try { await Task.Run(delegate { ReadLocal("/api/health", null); }); }
                catch (WebException)
                {
                    if (!IsDisposed) { allowClose = true; Close(); }
                }
                finally { checkingServer = false; }
            }
        };
        lifetime.Start();
    }

    private bool IsApplicationUrl(string address)
    {
        Uri candidate;
        return Uri.TryCreate(address, UriKind.Absolute, out candidate)
            && candidate.Scheme == origin.Scheme && candidate.Host == origin.Host
            && candidate.Port == origin.Port && String.IsNullOrEmpty(candidate.UserInfo);
    }

    private async void Initialize(object sender, EventArgs args)
    {
        try
        {
            if (await Task.WhenAny(ready, Task.Delay(30000)) != ready)
                throw new TimeoutException("The local application server did not start within 30 seconds.");
            Dictionary<string, object> configuration = await ready;
            if (IsDisposed || closing) return;
            origin = ParseOrigin((string)configuration["url"]);
            string root = Path.GetDirectoryName(Application.ExecutablePath);
            string runtime = Path.Combine(root, "tools", "webview2", "runtime");
            if (!File.Exists(Path.Combine(runtime, "msedgewebview2.exe")))
                throw new FileNotFoundException("The bundled WebView2 runtime is missing. Restore the complete application package.");
            // Override process-scoped WebView2 switches so an unrelated developer
            // environment cannot select installed Edge, a shared profile or debugging.
            foreach (string name in new[] { "WEBVIEW2_BROWSER_EXECUTABLE_FOLDER", "WEBVIEW2_USER_DATA_FOLDER",
                "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", "WEBVIEW2_RELEASE_CHANNEL_PREFERENCE",
                "WEBVIEW2_CHANNEL_SEARCH_KIND", "WEBVIEW2_RELEASE_CHANNELS", "WEBVIEW2_PIPE_FOR_SCRIPT_DEBUGGER" })
                Environment.SetEnvironmentVariable(name, null);
            CoreWebView2EnvironmentOptions options = new CoreWebView2EnvironmentOptions();
            options.AllowSingleSignOnUsingOSPrimaryAccount = false;
            options.AdditionalBrowserArguments = "--disable-sync --no-first-run --no-default-browser-check";
            CoreWebView2Environment environment = await CoreWebView2Environment.CreateAsync(
                runtime, (string)configuration["profile"], options);
            if (IsDisposed || closing) return;
            await view.EnsureCoreWebView2Async(environment);
            if (IsDisposed || closing) return;
            using (Process browser = Process.GetProcessById((int)view.CoreWebView2.BrowserProcessId))
            {
                if (!String.Equals(browser.MainModule.FileName, Path.Combine(runtime, "msedgewebview2.exe"),
                    StringComparison.OrdinalIgnoreCase))
                    throw new InvalidOperationException("The display engine is outside the bundled runtime folder.");
                if (attachBrowser != null) attachBrowser(browser);
            }
            CoreWebView2Settings settings = view.CoreWebView2.Settings;
            settings.AreDevToolsEnabled = false;
            settings.AreDefaultContextMenusEnabled = false;
            settings.IsStatusBarEnabled = false;
            settings.IsPasswordAutosaveEnabled = false;
            settings.IsGeneralAutofillEnabled = false;
            settings.AreBrowserAcceleratorKeysEnabled = false;
            settings.IsBuiltInErrorPageEnabled = false;
            view.CoreWebView2.WebMessageReceived += delegate(object source, CoreWebView2WebMessageReceivedEventArgs message)
            {
                if (!IsApplicationUrl(message.Source)) return;
                // The page can request only these two appearance values.
                // No host objects or arbitrary native operations are exposed.
                if (message.WebMessageAsJson == "\"theme:light\"") ApplyWindowTheme(true);
                else if (message.WebMessageAsJson == "\"theme:dark\"") ApplyWindowTheme(false);
            };
            view.CoreWebView2.NavigationStarting += delegate(object source, CoreWebView2NavigationStartingEventArgs navigation)
            {
                navigation.Cancel = !IsApplicationUrl(navigation.Uri);
            };
            view.CoreWebView2.NewWindowRequested += delegate(object source, CoreWebView2NewWindowRequestedEventArgs window)
            {
                window.Handled = true;
            };
            view.CoreWebView2.PermissionRequested += delegate(object source, CoreWebView2PermissionRequestedEventArgs permission)
            {
                permission.State = CoreWebView2PermissionState.Deny;
            };
            view.CoreWebView2.DownloadStarting += delegate(object source, CoreWebView2DownloadStartingEventArgs download)
            {
                download.Cancel = true;
            };
            view.CoreWebView2.NavigationCompleted += delegate(object source, CoreWebView2NavigationCompletedEventArgs navigation)
            {
                if (navigation.IsSuccess)
                {
                    status.Visible = false;
                    output("Desktop window: " + new JavaScriptSerializer().Serialize(new {
                        runtime = runtime, version = environment.BrowserVersionString,
                        browser_pid = view.CoreWebView2.BrowserProcessId,
                        profile = configuration["profile"] }));
                }
                else if (!closing)
                {
                    status.Text = "The application interface could not load: " + navigation.WebErrorStatus;
                }
            };
            view.CoreWebView2.ProcessFailed += delegate(object source, CoreWebView2ProcessFailedEventArgs failure)
            {
                if (!closing && failure.ProcessFailedKind == CoreWebView2ProcessFailedKind.BrowserProcessExited)
                {
                    status.Text = "The display engine stopped. Close and restart the application.";
                    status.Visible = true;
                }
            };
            view.CoreWebView2.Navigate(origin.AbsoluteUri);
        }
        catch (Exception error)
        {
            if (IsDisposed) return;
            failed = true;
            output("Native window failed: " + error);
            MessageBox.Show(this, error.Message, "Cartoon Downloader", MessageBoxButtons.OK, MessageBoxIcon.Error);
            Close();
        }
    }

    private string ReadLocal(string path, string token)
    {
        if (origin == null || origin.Scheme != "http" || origin.Host != "127.0.0.1"
            || !String.IsNullOrEmpty(origin.UserInfo))
            throw new InvalidOperationException("Invalid local application address.");
        HttpWebRequest request = (HttpWebRequest)WebRequest.Create(new Uri(origin, path));
        request.Proxy = null;
        request.Timeout = 5000;
        request.ReadWriteTimeout = 5000;
        if (token != null)
        {
            request.Method = "POST";
            request.ContentType = "application/json";
            request.Headers["X-CSRF-Token"] = token;
            byte[] body = Encoding.UTF8.GetBytes("{}");
            request.ContentLength = body.Length;
            using (Stream stream = request.GetRequestStream()) stream.Write(body, 0, body.Length);
        }
        using (WebResponse response = request.GetResponse())
        using (StreamReader reader = new StreamReader(response.GetResponseStream(), Encoding.UTF8))
            return reader.ReadToEnd();
    }

    private async void CloseApplication(object sender, FormClosingEventArgs args)
    {
        if (allowClose) return;
        args.Cancel = true;
        if (closing) return;
        closing = true;
        status.Text = "Closing application...";
        status.Visible = true;
        view.Enabled = false;
        try
        {
            if (origin == null)
            {
                if (await Task.WhenAny(ready, Task.Delay(30000)) != ready)
                    throw new TimeoutException("Still waiting for the application server.");
                origin = ParseOrigin((string)(await ready)["url"]);
            }
            await Task.Run(delegate
            {
                // Use exactly the same protected shutdown API as the sidebar.
                Dictionary<string, object> bootstrap = new JavaScriptSerializer { MaxJsonLength = 64 * 1024 * 1024 }
                    .Deserialize<Dictionary<string, object>>(ReadLocal("/api/bootstrap?compact=1", null));
                ReadLocal("/api/shutdown", (string)bootstrap["csrf_token"]);
            });
            if (server != null)
            {
                DateTime deadline = DateTime.UtcNow.AddSeconds(30);
                while (!server.HasExited && DateTime.UtcNow < deadline) await Task.Delay(100);
                if (!server.HasExited)
                    throw new TimeoutException("The application is still stopping its operations. Please wait and close the window again.");
            }
            allowClose = true;
            Close();
        }
        catch (Exception error)
        {
            if (IsDisposed) return;
            if (server != null && server.HasExited)
            {
                allowClose = true;
                Close();
                return;
            }
            closing = false;
            view.Enabled = true;
            status.Text = "Could not finish closing. Please try again.";
            output("Shutdown failed: " + error.Message);
            MessageBox.Show(this, error.Message, "Cartoon Downloader", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }

    protected override void Dispose(bool disposing)
    {
        if (disposing)
        {
            lifetime.Dispose();
            view.Dispose();
        }
        base.Dispose(disposing);
    }

    internal static Uri ParseOrigin(string address)
    {
        Uri result = new Uri(address);
        if (result.Scheme != "http" || result.Host != "127.0.0.1" || result.AbsolutePath != "/"
            || result.Port == 80 || !String.IsNullOrEmpty(result.Query) || !String.IsNullOrEmpty(result.Fragment)
            || !String.IsNullOrEmpty(result.UserInfo))
            throw new ArgumentException("Invalid local application address.");
        return result;
    }
}
