import ast
import textwrap
from odoo_naming.checker import OdooFieldNameChecker

def _lint(src: str):
    tree = ast.parse(textwrap.dedent(src))
    checker = OdooFieldNameChecker(tree)
    return list(checker.run())

def _has(errs, code):
    return any(code in msg for _, _, msg, _ in errs)

def test_boolean_rule():
    code = """
    from odoo import fields
    class X:
        active = fields.Boolean()
    """
    errs = _lint(code)
    assert _has(errs, "ODN100")

def test_date_rule_ok():
    code = """
    from odoo import fields
    class X:
        birth_date = fields.Date()
    """
    errs = _lint(code)
    assert not _has(errs, "ODN101")

def test_m2o_rule():
    code = """
    from odoo import fields
    class X:
        partner = fields.Many2one("res.partner")
    """
    errs = _lint(code)
    assert _has(errs, "ODN102")

def test_compute_inverse_search_rules():
    code = """
    from odoo import fields
    class X:
        is_active = fields.Boolean(compute="_compute_is_active",
                                   inverse="_inverse_is_active")
        company_id = fields.Many2one("res.company", search="_search_company_id")
        bad = fields.Boolean(compute="compute_bad", inverse="_inverse_bad")
    """
    errs = _lint(code)

    def has(code, field):
        return any(code in msg and field in msg for _, _, msg, _ in errs)

    assert not has("ODN110", "is_active")
    assert not has("ODN111", "is_active")

    assert not has("ODN112", "company_id")

    assert has("ODN100", "bad")
    assert has("ODN110", "bad")


def test_onchange_requires_prefix_and_fieldname():
    code = """
    from odoo import api
    class X:
        @api.onchange('company_id')
        def _onchange_company_id_extra(self):  # ok (prefix + field name)
            pass

        @api.onchange('company_id')
        def onchange_company_id(self):  # missing underscore + prefix
            pass
    """
    errs = _lint(code)
    assert _has(errs, "ODN113")

def test_constrains_requires_check_prefix():
    code = """
    from odoo import api
    class X:
        @api.constrains('name')
        def _check_name(self):
            pass

        @api.constrains('name')
        def validate_name(self):
            pass
    """
    errs = _lint(code)
    assert _has(errs, "ODN114")

def test_super_must_be_returned():
    code = """
    class X:
        def write(self, vals):
            super(X, self).write(vals)
            return True
    """
    errs = _lint(code)
    assert _has(errs, "ODN120")

def test_super_assign_then_return_ok():
    code = """
    class X:
        def write(self, vals):
            res = super(X, self).write(vals)
            return res
    """
    errs = _lint(code)
    assert not _has(errs, "ODN120")

def test_direct_return_super_call_ok():
    code = """
    class X:
        def name_get(self):
            return super().name_get()
    """
    errs = _lint(code)
    assert not _has(errs, "ODN120")
