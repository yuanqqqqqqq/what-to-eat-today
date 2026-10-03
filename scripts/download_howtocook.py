import json, os, time, urllib.request, urllib.parse, concurrent.futures

BASE = "https://raw.githubusercontent.com/Anduin2017/HowToCook/master/"
paths = json.load(open("data/raw/md_paths.json", encoding="utf-8"))
out_dir = "data/raw/md"
os.makedirs(out_dir, exist_ok=True)

def fetch(item):
    idx, path = item
    # percent-encode 中文路径，只编码路径分隔符以外的部分
    url = BASE + urllib.parse.quote(path)
    dst = os.path.join(out_dir, f"{idx:04d}.md")
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "san-can-agent"})
            with urllib.request.urlopen(req, timeout=30) as r:
                data = r.read()
            with open(dst, "wb") as f:
                f.write(data)
            return (idx, path, True, len(data))
        except Exception as e:
            if attempt == 2:
                return (idx, path, False, repr(e)[:80])
            time.sleep(1 + attempt)
    return (idx, path, False, "max retries")

items = list(enumerate(paths))
ok = fail = 0
failures = []
with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
    for idx, path, status, info in ex.map(fetch, items):
        if status:
            ok += 1
        else:
            fail += 1
            failures.append((idx, path, info))

# 保存索引映射（id -> 原始路径含菜名）
index = {f"{idx:04d}.md": p for idx, p in enumerate(paths)}
json.dump(index, open("data/raw/md_index.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)

print(f"下载完成: 成功 {ok}, 失败 {fail}, 总数 {len(paths)}")
if failures:
    print("失败样例(前5):")
    for f in failures[:5]:
        print(" ", f)
