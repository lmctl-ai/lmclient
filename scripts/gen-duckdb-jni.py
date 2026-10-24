#!/usr/bin/env python3
"""Derive Graal JNI callbacks from the pinned DuckDB JDBC JNI registration source.

Run after scripts/build-duckdb.sh fetches the pinned source. The checked-in
configuration also covers macOS/Windows builds that use bundled native engines.
"""
import json
from pathlib import Path
import re

root = Path(__file__).resolve().parents[1]
source = (root / "third_party/duckdb-java/src/jni/refs.cpp").read_text(encoding="utf-8")
class_names = dict(re.findall(r'(\w+)\s*=\s*make_class_ref\(env,\s*"([^"]+)"\)', source))
entries = {}

def type_name(descriptor):
    primitives = {"Z":"boolean", "B":"byte", "C":"char", "S":"short", "I":"int", "J":"long", "F":"float", "D":"double", "V":"void"}
    arrays = len(descriptor) - len(descriptor.lstrip("["))
    descriptor = descriptor[arrays:]
    name = descriptor[1:-1].replace("/", ".") if descriptor.startswith("L") else primitives[descriptor]
    return name + "[]" * arrays

def entry(name):
    name = type_name(name) if name.startswith("[") else name.replace("/", ".")
    return entries.setdefault(name, {"name":name})

for name in class_names.values():
    entry(name)

def parameter_types(signature):
    assert signature.startswith("("), signature
    return [type_name(token) for token in re.findall(r'\[*(?:L[^;]+;|[ZBCSIJFD])', signature[1:signature.index(")")])]

literal = r'((?:"[^"\n]*"\s*)+)'
for pattern in (
    r'(?:get_method_id|get_static_method_id|make_static_method_call_ref)\(env,\s*(\w+),\s*"([^"]+)",\s*' + literal + r'\)',
    r'env->Get(?:Static)?MethodID\(\s*(\w+),\s*"([^"]+)",\s*' + literal + r'\)',
):
    for variable, name, strings in re.findall(pattern, source):
        signature = "".join(re.findall(r'"([^"]*)"',strings))
        declaring = class_names[variable]
        # This inherited callback is registered once on its declaring class.
        if declaring == "org/duckdb/DuckDBTimestampTZ" and name == "getMicrosEpoch":
            declaring = "org/duckdb/DuckDBTimestamp"
        method = {"name": name, "parameterTypes": parameter_types(signature)}
        methods = entry(declaring).setdefault("methods",[])
        if method not in methods:
            methods.append(method)
for variable, name in re.findall(r'(?:get_field_id|make_static_object_field_ref)\(env,\s*(\w+),\s*"([^"]+)"', source):
    field = {"name":name}
    fields = entry(class_names[variable]).setdefault("fields",[])
    if field not in fields:
        fields.append(field)
for name in ("java/sql/SQLException", "java/sql/SQLTimeoutException", "java/lang/RuntimeException", "java/lang/NoSuchMethodError"):
    entry(name).setdefault("methods",[]).append({"name":"<init>","parameterTypes":["java.lang.String"]})
output = root / "src/main/resources/META-INF/native-image/ai.lmctl/lmdb-duckdb/jni-config.json"
output.parent.mkdir(parents=True,exist_ok=True)
output.write_text(json.dumps(sorted(entries.values(),key=lambda item:item["name"]),indent=2) + "\n",encoding="utf-8")
print(f"DuckDB JNI callbacks: {len(entries)} classes, {sum(len(x.get('methods',[])) for x in entries.values())} methods")
