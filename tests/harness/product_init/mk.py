"""K 시나리오용 제품 저장소 2개(승인 / 미승인) 생성. tests/product_init_test.py의 픽스처 헬퍼를 씁니다."""
import os, sys
from pathlib import Path
W = Path(sys.argv[1]); ENGINE = Path(os.environ["ENGINE"])
sys.path.insert(0, str(ENGINE / "tests"))
import product_init_test as T  # noqa: E402
T.WORK = W / "work"
for name, st in (("k2_main", "approved"), ("k2_unapproved", "awaiting_approval")):
    d = T.make_product(name, planning_status=st)
    (d / ".claude/skills").mkdir(parents=True)
    os.symlink(ENGINE / "skills/product-init", d / ".claude/skills/product-init")
    os.symlink(ENGINE / "skills/product-start", d / ".claude/skills/product-start")
    print(d)
