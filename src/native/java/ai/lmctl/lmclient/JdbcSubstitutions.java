package ai.lmctl.lmclient;

import com.oracle.svm.core.annotate.Alias;
import com.oracle.svm.core.annotate.Substitute;
import com.oracle.svm.core.annotate.TargetClass;
import org.graalvm.nativeimage.Platform;
import org.graalvm.nativeimage.Platforms;
import org.graalvm.nativeimage.c.function.CFunction;
import org.graalvm.word.PointerBase;
import org.graalvm.word.WordFactory;
import com.oracle.svm.core.jni.functions.JNIFunctionTables;
import com.oracle.svm.core.jni.headers.JNIJavaVM;

@Platforms(Platform.LINUX.class)
final class StaticJdbcEntrypoints {
    @CFunction("JNI_OnLoad_sqlitejdbc") static native int sqlite(JNIJavaVM vm, PointerBase reserved);
    @CFunction("JNI_OnLoad_duckdb_java") static native int duckdb(JNIJavaVM vm, PointerBase reserved);
    static void initialize(boolean sqlite) {
        JNIJavaVM vm = JNIFunctionTables.singleton().getGlobalJavaVM();
        int version = sqlite ? sqlite(vm,WordFactory.nullPointer()) : duckdb(vm,WordFactory.nullPointer());
        if (version < 0) throw new UnsatisfiedLinkError("bundled database JNI initialization failed");
    }
}

@Platforms(Platform.LINUX.class)
@TargetClass(className = "org.duckdb.DuckDBNative")
final class StaticDuckDBLoader {
    @Substitute private static void loadNativeLibrary() { StaticJdbcEntrypoints.initialize(false); }
}

@Platforms(Platform.LINUX.class)
@TargetClass(className = "org.sqlite.SQLiteJDBCLoader")
final class StaticSQLiteLoader {
    @Alias private static boolean extracted;
    @Substitute public static synchronized boolean initialize() {
        if (!extracted) { StaticJdbcEntrypoints.initialize(true); extracted = true; }
        return true;
    }
}

