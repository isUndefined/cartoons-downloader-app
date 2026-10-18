using System;
using System.Runtime.InteropServices;

// IFileOperation supports Shell namespace items (including Windows MTP).
// Preserve the native vtable order, including methods we do not call.
public static class MtpCopy
{
    [ComImport, Guid("43826D1E-E718-42EE-BC55-A1E261C37BFE"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface IShellItem { }

    [ComImport, Guid("947AAB5F-0A5C-4C13-B4D6-4BF7836FC9F8"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface IFileOperation
    {
        void Advise(IFileOperationProgressSink sink, out uint cookie);
        void Unadvise(uint cookie);
        void SetOperationFlags(uint flags);
        void SetProgressMessage([MarshalAs(UnmanagedType.LPWStr)] string message);
        void SetProgressDialog(IntPtr dialog);
        void SetProperties(IntPtr properties);
        void SetOwnerWindow(IntPtr window);
        void ApplyPropertiesToItem(IShellItem item);
        void ApplyPropertiesToItems(IntPtr items);
        void RenameItem(IShellItem item, [MarshalAs(UnmanagedType.LPWStr)] string name, IntPtr sink);
        void RenameItems(IntPtr items, [MarshalAs(UnmanagedType.LPWStr)] string name);
        void MoveItem(IShellItem item, IShellItem folder, [MarshalAs(UnmanagedType.LPWStr)] string name, IntPtr sink);
        void MoveItems(IntPtr items, IShellItem folder);
        void CopyItem(IShellItem item, IShellItem folder, [MarshalAs(UnmanagedType.LPWStr)] string name, IntPtr sink);
        void CopyItems(IntPtr items, IShellItem folder);
        void DeleteItem(IShellItem item, IntPtr sink);
        void DeleteItems(IntPtr items);
        void NewItem(IShellItem folder, uint attributes, [MarshalAs(UnmanagedType.LPWStr)] string name,
                     [MarshalAs(UnmanagedType.LPWStr)] string template, IntPtr sink);
        void PerformOperations();
        void GetAnyOperationsAborted([MarshalAs(UnmanagedType.Bool)] out bool aborted);
    }

    // Native vtable order from shobjidl_core.h. The unused Shell item/string
    // pointers stay opaque; only HRESULTs and item completion are consumed.
    [ComVisible(true), Guid("04B0F1A7-9490-44BC-96E1-4296A31252E2"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    public interface IFileOperationProgressSink
    {
        [PreserveSig] int StartOperations();
        [PreserveSig] int FinishOperations(int result);
        [PreserveSig] int PreRenameItem(uint flags, IntPtr item, IntPtr name);
        [PreserveSig] int PostRenameItem(uint flags, IntPtr item, IntPtr name, int result, IntPtr created);
        [PreserveSig] int PreMoveItem(uint flags, IntPtr item, IntPtr folder, IntPtr name);
        [PreserveSig] int PostMoveItem(uint flags, IntPtr item, IntPtr folder, IntPtr name, int result, IntPtr created);
        [PreserveSig] int PreCopyItem(uint flags, IntPtr item, IntPtr folder, IntPtr name);
        [PreserveSig] int PostCopyItem(uint flags, IntPtr item, IntPtr folder, IntPtr name, int result, IntPtr created);
        [PreserveSig] int PreDeleteItem(uint flags, IntPtr item);
        [PreserveSig] int PostDeleteItem(uint flags, IntPtr item, int result, IntPtr created);
        [PreserveSig] int PreNewItem(uint flags, IntPtr folder, IntPtr name);
        [PreserveSig] int PostNewItem(uint flags, IntPtr folder, IntPtr name, IntPtr template, uint attributes, int result, IntPtr created);
        [PreserveSig] int UpdateProgress(uint total, uint completed);
        [PreserveSig] int ResetTimer();
        [PreserveSig] int PauseTimer();
        [PreserveSig] int ResumeTimer();
    }

    [ComVisible(true), ClassInterface(ClassInterfaceType.None)]
    public sealed class CopyProgressSink : IFileOperationProgressSink
    {
        public int Error;
        public bool CopyCompleted;

        private int Record(int result)
        {
            if (result < 0 && Error == 0) Error = result;
            return 0;
        }

        public int StartOperations() { return 0; }
        public int FinishOperations(int result) { return Record(result); }
        public int PreRenameItem(uint flags, IntPtr item, IntPtr name) { return 0; }
        public int PostRenameItem(uint flags, IntPtr item, IntPtr name, int result, IntPtr created) { return 0; }
        public int PreMoveItem(uint flags, IntPtr item, IntPtr folder, IntPtr name) { return 0; }
        public int PostMoveItem(uint flags, IntPtr item, IntPtr folder, IntPtr name, int result, IntPtr created) { return 0; }
        public int PreCopyItem(uint flags, IntPtr item, IntPtr folder, IntPtr name) { return 0; }
        public int PostCopyItem(uint flags, IntPtr item, IntPtr folder, IntPtr name, int result, IntPtr created)
        {
            CopyCompleted = true;
            return Record(result);
        }
        public int PreDeleteItem(uint flags, IntPtr item) { return 0; }
        public int PostDeleteItem(uint flags, IntPtr item, int result, IntPtr created) { return 0; }
        public int PreNewItem(uint flags, IntPtr folder, IntPtr name) { return 0; }
        public int PostNewItem(uint flags, IntPtr folder, IntPtr name, IntPtr template, uint attributes, int result, IntPtr created) { return 0; }
        public int UpdateProgress(uint total, uint completed) { return 0; }
        public int ResetTimer() { return 0; }
        public int PauseTimer() { return 0; }
        public int ResumeTimer() { return 0; }
    }

    [DllImport("shell32.dll", CharSet = CharSet.Unicode, PreserveSig = false)]
    private static extern void SHCreateItemFromParsingName(string path, IntPtr context, ref Guid iid,
                                                          [MarshalAs(UnmanagedType.Interface)] out IShellItem item);

    [DllImport("shell32.dll", PreserveSig = false)]
    private static extern void SHGetIDListFromObject([MarshalAs(UnmanagedType.IUnknown)] object item,
                                                    out IntPtr pidl);

    [DllImport("shell32.dll", PreserveSig = false)]
    private static extern void SHCreateItemFromIDList(IntPtr pidl, ref Guid iid,
                                                     [MarshalAs(UnmanagedType.Interface)] out IShellItem item);

    private static IShellItem FolderItem(object folder)
    {
        IntPtr pidl = IntPtr.Zero;
        try
        {
            SHGetIDListFromObject(folder, out pidl);
            Guid iid = typeof(IShellItem).GUID;
            IShellItem item;
            SHCreateItemFromIDList(pidl, ref iid, out item);
            return item;
        }
        catch (Exception error)
        {
            throw new InvalidOperationException("Cannot resolve destination Shell folder identity", error);
        }
        finally
        {
            if (pidl != IntPtr.Zero) Marshal.FreeCoTaskMem(pidl);
        }
    }

    private static IShellItem ParseItem(string path, string role)
    {
        try
        {
            Guid iid = typeof(IShellItem).GUID;
            IShellItem item;
            SHCreateItemFromParsingName(path, IntPtr.Zero, ref iid, out item);
            return item;
        }
        catch (Exception error)
        {
            throw new InvalidOperationException("Cannot open " + role + " Shell item: " + path, error);
        }
    }

    public static void Copy(string sourcePath, string destinationPath, string name)
    {
        CopyCore(sourcePath, ParseItem(destinationPath, "destination"), name);
    }

    // MTP FolderItem.Path contains device object IDs which are not necessarily
    // parseable display names. Preserve the Shell object's PIDL instead.
    public static void CopyToFolder(string sourcePath, object destinationFolder, string name)
    {
        CopyCore(sourcePath, FolderItem(destinationFolder), name);
    }

    private static void CopyCore(string sourcePath, IShellItem destination, string name)
    {
        IShellItem source = null;
        IFileOperation operation = null;
        CopyProgressSink progress = new CopyProgressSink();
        uint cookie = 0;
        bool advised = false;
        try
        {
            source = ParseItem(sourcePath, "source");
            operation = (IFileOperation)Activator.CreateInstance(Type.GetTypeFromCLSID(
                new Guid("3AD05575-8857-4850-9277-11B85BDB8E09")));
            // Silent, no confirmations, no directory confirmation, no error UI.
            operation.SetOperationFlags(0x0614);
            operation.Advise(progress, out cookie);
            advised = true;
            operation.CopyItem(source, destination, name, IntPtr.Zero);
            Exception copyError = null;
            try
            {
                operation.PerformOperations();
            }
            catch (COMException error)
            {
                copyError = error;
            }
            finally
            {
                bool aborted;
                try
                {
                    operation.GetAnyOperationsAborted(out aborted);
                }
                finally
                {
                    if (progress.Error < 0)
                        throw new InvalidOperationException(
                            "MTP copy failed (0x" + progress.Error.ToString("X8") + "): " +
                            Marshal.GetExceptionForHR(progress.Error).Message);
                    // Query cancellation even on failure, but preserve the
                    // original HRESULT instead of replacing it with "aborted".
                    if (copyError != null)
                        throw new InvalidOperationException(
                            "MTP copy failed (0x" + copyError.HResult.ToString("X8") + "): " + copyError.Message,
                            copyError);
                }
                if (aborted) throw new InvalidOperationException("MTP copy was aborted");
                if (!progress.CopyCompleted)
                    throw new InvalidOperationException("MTP copy returned no item completion receipt");
            }
        }
        finally
        {
            if (operation != null && advised)
            {
                try { operation.Unadvise(cookie); }
                catch (COMException) { } // Cleanup must not hide the copy error.
            }
            GC.KeepAlive(progress);
            if (operation != null) Marshal.FinalReleaseComObject(operation);
            if (destination != null) Marshal.FinalReleaseComObject(destination);
            if (source != null) Marshal.FinalReleaseComObject(source);
        }
    }
}
