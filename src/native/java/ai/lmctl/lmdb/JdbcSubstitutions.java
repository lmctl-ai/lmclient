package ai.lmctl.lmdb;

import com.oracle.svm.core.annotate.Alias;
import com.oracle.svm.core.annotate.Substitute;
import com.oracle.svm.core.annotate.TargetClass;
import org.graalvm.nativeimage.Platform;
import org.graalvm.nativeimage.Platforms;

@Platforms(Platform.LINUX.class)
@TargetClass(className = "org.duckdb.DuckDBNative")
final class StaticDuckDBLoader {
    @Substitute private static void loadNativeLibrary() { System.loadLibrary("duckdb_java"); }
}

@Platforms(Platform.LINUX.class)
@TargetClass(className = "org.sqlite.SQLiteJDBCLoader")
final class StaticSQLiteLoader {
    @Alias private static boolean extracted;
    @Substitute public static synchronized boolean initialize() {
        if (!extracted) { System.loadLibrary("sqlitejdbc"); extracted = true; }
        return true;
    }
}

