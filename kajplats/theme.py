"""Dark Qt stylesheet.

A light bulb controller is usually opened in a dim room, and a dark surface is
also the only honest backdrop for judging a colour swatch — a bright chrome
would wash the previews out.
"""

STYLESHEET = """
QWidget {
    background: #101217;
    color: #e8eaf0;
    font-size: 13px;
}

/* Labels and plain container widgets inherit whatever surface they sit on,
   so a card's background shows through instead of a window-coloured band. */
QLabel, #swatches, #swatches QWidget {
    background: transparent;
}

#title {
    font-size: 19px;
    font-weight: 600;
    letter-spacing: 1.5px;
}

#pill {
    padding: 3px 10px;
    border-radius: 9px;
    font-size: 11px;
    background: #262a33;
    color: #9aa2b1;
}
#pill[state="ok"]  { background: #15311f; color: #68d391; }
#pill[state="bad"] { background: #38191c; color: #f08a8a; }

#bulbCard {
    background: #171a21;
    border: 1px solid #242832;
    border-radius: 14px;
}
#bulbCard[offline="true"] { border: 1px solid #4a2b2b; }

#bulbName {
    background: transparent;
    border: none;
    border-bottom: 1px solid transparent;
    font-size: 15px;
    font-weight: 600;
    padding: 2px 0;
}
#bulbName:hover  { border-bottom: 1px solid #2f3440; }
#bulbName:focus  { border-bottom: 1px solid #5b8cff; }

#cardStatus, #statusLine, #dialogNote {
    color: #7d8695;
    font-size: 11px;
}
#statusLine { padding-top: 2px; }

#placeholder {
    background: transparent;
    color: #6d7686;
    font-size: 14px;
    border: 1px dashed #2a2f3a;
    border-radius: 14px;
    padding: 40px;
}

#sliderLabel {
    color: #a6aebd;
    font-size: 11px;
    letter-spacing: 0.4px;
}

QPushButton {
    background: #20242e;
    border: 1px solid #2c313d;
    border-radius: 8px;
    padding: 6px 12px;
    color: #dfe3eb;
}
QPushButton:hover   { background: #272c38; }
QPushButton:pressed { background: #1b1f27; }
QPushButton:disabled { color: #5a6170; background: #191c23; }

#powerButton:checked {
    background: #2f4d8f;
    border: 1px solid #4a74d0;
    color: #ffffff;
    font-weight: 600;
}

#segmentLeft, #segmentRight {
    padding: 5px 16px;
    background: #1b1f27;
    border: 1px solid #2c313d;
}
#segmentLeft  { border-top-right-radius: 0; border-bottom-right-radius: 0; }
#segmentRight { border-top-left-radius: 0; border-bottom-left-radius: 0;
                border-left: none; }
#segmentLeft:checked, #segmentRight:checked {
    background: #2b3240;
    color: #ffffff;
    border: 1px solid #45506a;
}

QCheckBox { color: #c6ccd8; }
QCheckBox::indicator {
    width: 15px; height: 15px;
    border-radius: 4px;
    border: 1px solid #39404f;
    background: #1b1f27;
}
QCheckBox::indicator:checked {
    background: #4a74d0;
    border: 1px solid #5b8cff;
}

QLineEdit {
    background: #1b1f27;
    border: 1px solid #2c313d;
    border-radius: 7px;
    padding: 6px 9px;
    selection-background-color: #3a5aa0;
}
QLineEdit:focus { border: 1px solid #5b8cff; }

QToolTip {
    background: #20242e;
    color: #e8eaf0;
    border: 1px solid #343a47;
    padding: 4px 7px;
}
"""
