#!/bin/bash
# 跑全部套件。
#
# 两条纪律，都是被真事咬出来的：
#
# ① 脚本崩掉和断言失败必须分开。
#    以前那个一行 for 循环只数 ✓/✗，脚本中途崩了它照样报「✗0」——
#    看起来是绿的。这里认退出码。
#
# ② 被测的那个 dist 本身必须是干净的。
#    migrate.mjs / swupdate.mjs 会把 dist 换成别的版本来测升级路径。
#    它俩一旦中途崩了，dist 就停在**别的版本**上（migrate 更狠：
#    先 rm -rf 再 cp，源没了就等于把 App 删了）——后面每一条套件
#    从此测的都是错东西。上一轮就是这么来的：pend / review / pill /
#    rescue / talk 一起变红，而它们单独跑全是绿的，我差点去改没坏的代码。
#    反过来同样成立：它可以让该红的变绿。
#    所以每跑完一条就比对一次，动过就吼一声并还原。
cd "$(dirname "$0")"
DIST="$(cd "$(dirname "$0")/.." && pwd)/dist"
PRISTINE=$(mktemp -d)
if [ ! -f "$DIST/index.html" ]; then
  echo "dist 里没有 index.html —— 先 npm run build"; exit 2
fi
cp -r "$DIST/." "$PRISTINE/"
stamp () { find "$1" -type f -printf '%P %s\n' 2>/dev/null | sort | md5sum | cut -d' ' -f1; }
BASE=$(stamp "$PRISTINE")
trap 'rm -rf "$PRISTINE"' EXIT

fail=0; asserts=0; suites=0; probes=0
for f in "$@"; do
  out=$(node "$f.mjs" 2>&1); code=$?
  y=$(echo "$out" | grep -c '^✓'); n=$(echo "$out" | grep -c '^✗')
  if [ $code -ne 0 ] && [ "$n" = "0" ]; then
    printf "%-13s ✓%-3s 💥 脚本崩了（退出码 %s）\n" "$f" "$y" "$code"
    echo "$out" | tail -4 | sed 's/^/                /'
    fail=1
  elif [ "$n" != "0" ]; then
    printf "%-13s ✓%-3s ✗%s\n" "$f" "$y" "$n"
    echo "$out" | grep '^✗' | head -3 | sed 's/^/                /'
    fail=1
  elif [ "$y" = "0" ]; then
    # 一条断言都没出的脚本不叫「通过」，它只是没说话。
    # 以前它跟真绿一样印成「✓0」，我照着数就把探针也算进了「全绿 N 条」
    printf "%-13s ·  探针，没有断言\n" "$f"
    probes=$((probes+1))
  else
    printf "%-13s ✓%s\n" "$f" "$y"
    asserts=$((asserts+$y)); suites=$((suites+1))
  fi
  if [ "$(stamp "$DIST")" != "$BASE" ]; then
    # migrate / swupdate 本来就要换 dist 才能测升级路径，所以「换过」不算错，
    # 换完没还原干净才算。真正要保证的是**下一条套件测的是对的东西**。
    # 这里不把它算成失败：一条永远微红的检查等于没有检查。
    printf "%-13s ↩︎ 这条动过 dist（升级路径要换版本），已还原成基线\n" ""
    rm -rf "$DIST"; mkdir -p "$DIST"; cp -r "$PRISTINE/." "$DIST/"
    if [ "$(stamp "$DIST")" != "$BASE" ]; then
      printf "%-13s ⚠️  还原失败 —— 后面每一条测的都是错东西，停在这儿\n" ""
      exit 2
    fi
  fi
done
echo "—— $suites 个套件 / $asserts 条断言，另有 $probes 个探针（不出断言，不算数） ——"
[ $fail = 0 ] && echo "—— 全绿 ——" || echo "—— 有问题 ——"
exit $fail
