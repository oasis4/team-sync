#!/bin/bash
# Baut ein frisches Testteam: ein Remote, zwei Klone, Channel eingerichtet.
set -e
SIM="$1"; PLUGIN="$2"
rm -rf "$SIM/team"; mkdir -p "$SIM/team"; cd "$SIM/team"
git init -q --bare -b main remote.git
git clone -q remote.git vorlage 2>/dev/null
cd vorlage
git config user.name "Vorlage"; git config user.email v@x.test
mkdir -p api shared frontend
touch api/__init__.py shared/__init__.py frontend/__init__.py
cat > shared/models.py <<'PY'
from dataclasses import dataclass


@dataclass
class Order:
    id: int
    total: float  # Betrag in Euro
PY
cat > api/orders.py <<'PY'
from shared.models import Order

ORDERS = {
    1: Order(id=1, total=12.34),
    2: Order(id=2, total=5.0),
}


def get_order(order_id):
    """Liefert eine Bestellung so, wie die API sie ausgibt."""
    order = ORDERS[order_id]
    return {"id": order.id, "total": order.total}
PY
cat > frontend/render.py <<'PY'
"""Darstellung von Bestellungen im Frontend."""
PY
printf '# Shop\n\nBackend in api/, Frontend in frontend/, gemeinsame Modelle in shared/.\n' > README.md
git add -A && git commit -qm "Startstand" && git push -q -u origin main 2>/dev/null
cd ..
for wer in "lars:Lars Becker" "max:Max Mustermann"; do
  d=${wer%%:*}; n=${wer#*:}
  git clone -q remote.git $d 2>/dev/null
  git -C $d config user.name "$n"; git -C $d config user.email "$d@x.test"
  (cd $d && python3 "$PLUGIN/scripts/setup_channel.py" > /dev/null)
done
rm -rf vorlage
echo "Team aufgebaut in $SIM/team"
