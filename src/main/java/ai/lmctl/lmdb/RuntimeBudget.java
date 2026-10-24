package ai.lmctl.lmdb;

/** Apply immutable heap limits at startup, using the same executable for native restarts. */
public final class RuntimeBudget {
    private RuntimeBudget() {}
    public static void configure(long bytes,String[] arguments) throws Exception {
        // Reserve a quarter of the allocation budget for embedded C database engines.
        if (bytes < 16L * 1024 * 1024)
            throw new ai.lmctl.lmdb.core.DatabaseException("LMDB_MAX_MEMORY_MB must allow at least 16 MiB for the Java runtime");
        long heapMegabytes = bytes / (1024 * 1024) * 3 / 4 / 4 * 4;
        long heapBytes = heapMegabytes * 1024 * 1024;
        // JVMs may round the maximum to a GC region boundary. A verified child does
        // not restart again; the marker is also checked against its actual heap.
        String marker = System.getenv("LMDB_INTERNAL_HEAP_BYTES");
        long actual = Runtime.getRuntime().maxMemory();
        if (actual <= heapBytes) return;
        if (Long.toString(heapBytes).equals(marker))
            throw new ai.lmctl.lmdb.core.DatabaseException("LMDB_MAX_MEMORY_MB heap startup limit was not applied");
        String executable = ProcessHandle.current().info().command().orElseThrow();
        var command = new java.util.ArrayList<String>();
        command.add(executable);
        command.add("-Xmx" + heapMegabytes + "m");
        if (!"runtime".equals(System.getProperty("org.graalvm.nativeimage.imagecode"))) {
            command.add("-cp"); command.add(System.getProperty("java.class.path")); command.add(Main.class.getName());
        }
        java.util.Collections.addAll(command,arguments);
        var process = new ProcessBuilder(command).inheritIO();
        process.environment().put("LMDB_INTERNAL_HEAP_BYTES", Long.toString(heapBytes));
        int status = process.start().waitFor();
        System.exit(status);
    }
}
