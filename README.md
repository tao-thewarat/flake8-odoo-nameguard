# flake8-odoo-nameguard

Flake8 plugin สำหรับ enforce naming conventions ของ Odoo 18:

## Field rules
- Boolean → `is_*`
- Date → `*_date`
- Many2one → `*_id`
- Many2many → `*_ids`

## Method rules
- `compute="_compute_<field>"`
- `inverse="_inverse_<field>"`
- `search="_search_<field>"`
- `@api.onchange('x')` → `_onchange_x...`
- `@api.constrains('y')` → `_check_y...`

## Super rules
- ถ้าเรียก `super(...).method(...)` ต้อง `return` ผลลัพธ์ออก (ODN120)

---

### install (local)
```bash
pip install -e .
```
