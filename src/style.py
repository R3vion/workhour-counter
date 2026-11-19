"""Colors and the Qt style sheet."""

BACKGROUND = "#222222"

# Digit colors
ACTIVE_ORANGE = "#ff5a1a"
INACTIVE_BLUE = "#2459f0"
MONEY_GREEN = "#16a447"
TIME_WHITE = "#f2f2f2"
LIMIT_GREY = "#b4b4b4"
CAPTION_GREY = "#8c8c8c"
DEV_WARNING = "#ff9f43"

STYLE_SHEET = f"""
QWidget {{
    background: {BACKGROUND};
    color: #dddddd;
}}
QLabel#caption {{ color: {CAPTION_GREY}; }}
QLabel#limit   {{ color: {LIMIT_GREY}; }}

QPushButton {{
    background: #353535;
    border: 1px solid #484848;
    border-radius: 6px;
    padding: 6px 14px;
    color: #e6e6e6;
}}
QPushButton:hover   {{ background: #3d3d3d; }}
QPushButton:pressed {{ background: #303030; }}
QPushButton:disabled {{ color: #5e5e5e; background: #313131; border-color: #3a3a3a; }}

QPushButton#start, QPushButton#stop {{
    min-width: 132px;
    min-height: 36px;
    font-size: 13px;
    font-weight: 600;
}}
QPushButton#start {{ color: #7ee2a0; border-color: #3f6e50; }}
QPushButton#stop  {{ color: #f08a8a; border-color: #7a4646; }}
QPushButton#start:disabled, QPushButton#stop:disabled {{
    color: #5e5e5e; background: #313131; border-color: #3a3a3a;
}}

QPushButton#invoices {{
    font-size: 11px;
    font-weight: 600;
    padding: 4px 16px;
    color: #c8c8c8;
}}

QPushButton#build, QPushButton#build_dev {{
    background: transparent;
    border: none;
    padding: 0;
    font-size: 10px;
    text-align: left;
}}
QPushButton#build       {{ color: #6f6f6f; }}
QPushButton#build:hover {{ color: #a8a8a8; }}
QPushButton#build_dev   {{ color: {DEV_WARNING}; }}

QCheckBox {{ color: #b0b0b0; spacing: 6px; }}
QCheckBox::indicator {{
    width: 13px; height: 13px;
    border: 1px solid #5c5c5c; border-radius: 3px; background: #333333;
}}
QCheckBox::indicator:checked {{ background: #d0d0d0; border-color: #d0d0d0; }}

QComboBox, QSpinBox, QDoubleSpinBox {{
    background: #363636;
    border: 1px solid #4a4a4a;
    border-radius: 4px;
    padding: 4px 6px;
    min-height: 20px;
}}
QTableWidget {{
    background: #262626;
    gridline-color: #333333;
    border: 1px solid #3a3a3a;
    selection-background-color: #3d4a5c;
}}
QHeaderView::section {{
    background: #2f2f2f;
    color: #b8b8b8;
    border: none;
    border-bottom: 1px solid #3a3a3a;
    padding: 4px 6px;
}}

QComboBox QAbstractItemView {{
    background: #363636;
    selection-background-color: #4a4a4a;
}}
"""
