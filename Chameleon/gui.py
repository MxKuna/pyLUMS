class Chameleon(DeviceOverZeroMQ):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Default values for GUI display
        self.keyswitch = 0
        self.busy = ""
        self.tuning = 0
        self.lasing = 0
        self.current_wavelength = 2137
        self.fixed_power = 2137
        self.tunable_power = 2137
        self.fixed_shutter_open = False
        self.tunable_shutter_open = False

        self.dict = {
            "keyswitch": {"ON": 1, "OFF": 0}, 
            "tuning": {"Tuning...": 1, "Tuned": 0}, 
            "lasing": {"Lasing!": 1, "Not Lasing": 0}   
        }

    def createDock(self, parentWidget, menu=None):
        # Create the dock widget
        dock = QDockWidget("Chameleon Laser Control", parentWidget)
        
        # Create a main widget to hold the content
        main_widget = QWidget(parentWidget)
        
        # Create a tab widget
        tab_widget = QTabWidget()
                        
        # First Tab - 2x2 Grid of Smaller Groups with Additional Row
        first_tab = QWidget()
        first_tab_layout = QVBoxLayout()
        
        # Create outer group for grid
        grid_outer_group = QGroupBox("Processes")
        grid_outer_group_layout = QVBoxLayout()
        
        # Create grid layout directly
        grid_layout = QGridLayout()
        
        # Create 2x2 grid of groups
        group_names = {
            "KEYSWITCH": self.keyswitch, 
            "BUSY": self.busy, 
            "TUNING": self.tuning, 
            "LASING": self.lasing   
        }

        for i in range(2):
            for j in range(2):
                sub_group = QGroupBox(list(group_names.keys())[i*2 + j])
                sub_group_layout = QVBoxLayout()
                
                sub_group_text_box = QLineEdit(f"{list(group_names.values())[i*2 + j]}")
                sub_group_text_box.setReadOnly(True)
                sub_group_text_box.setStyleSheet("""
                    background-color: #f0f0f0;
                    color: black;
                    border: 1px solid #a0a0a0;
                    padding: 4px;
                """)
        
                sub_group_layout.addWidget(sub_group_text_box)
                sub_group.setLayout(sub_group_layout)
                grid_layout.addWidget(sub_group, i, j)
        
        grid_outer_group_layout.addLayout(grid_layout)
        grid_outer_group.setLayout(grid_outer_group_layout)
        first_tab_layout.addWidget(grid_outer_group, 2)
        
        # New Group for Checkboxes
        checkbox_group = QGroupBox("Alignment Mode")
        checkbox_layout = QHBoxLayout()
        
        # Label for the checkbox row
        checkbox_label = QLabel("Check to enable:")
        
        # Two Checkboxes
        checkbox1 = QtWidgets.QCheckBox("FIXED")
        checkbox2 = QtWidgets.QCheckBox("TUNABLE")
        
        checkbox_layout.addWidget(checkbox_label)
        checkbox_layout.addWidget(checkbox1)
        checkbox_layout.addWidget(checkbox2)
        
        checkbox_group.setLayout(checkbox_layout)
        first_tab_layout.addWidget(checkbox_group, 1)
        
        first_tab.setLayout(first_tab_layout)
        
        # Second Tab - Button on Top, Group Below Divided Vertically
        second_tab = QWidget()
        second_tab_layout = QVBoxLayout()
        
        # Red Rectangle Label
        red_rectangle = QLabel("LASING!")
        red_rectangle.setAlignment(Qt.AlignCenter)
        red_rectangle.setStyleSheet("""
            background-color: red; 
            color: white; 
            font-weight: bold; 
            font-size: 20px; 
            border: 3px solid darkred; 
            padding: 4px;
            border-radius: 10px;
        """)
        red_rectangle.setMinimumHeight(20)  # Ensure minimum height
        red_rectangle.setMaximumHeight(35)  # Ensure max height
        
        # Main Group for Second Tab
        second_main_group = QGroupBox("SHUTTERS")
        second_main_group_layout = QHBoxLayout()
        
        # left Subgroup
        left_subgroup = QGroupBox("FIXED")
        left_subgroup_layout = QVBoxLayout()
        
        left_label = QLabel("1030 nm")
        left_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        left_label.setAlignment(Qt.AlignCenter)
        left_lcd = QLCDNumber()
        left_lcd.setDigitCount(5)
        left_lcd.setStyleSheet("color: blue; background-color: black;")
        left_lcd.setMinimumHeight(40)
        left_lcd.display(12345)
        
        self.left_button = QPushButton("OPEN")
        self.left_button.setMinimumHeight(32)
        
        left_subgroup_layout.addWidget(left_label)
        left_subgroup_layout.addWidget(left_lcd)
        left_subgroup_layout.addWidget(self.left_button)
        left_subgroup.setLayout(left_subgroup_layout)
        
        # Bottom Subgroup
        right_subgroup = QGroupBox("TUNABLE")
        right_subgroup_layout = QVBoxLayout()
        
        self.right_label = QLabel(f"{self.current_wavelength} nm")
        self.right_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        self.right_label.setAlignment(Qt.AlignCenter)
        right_lcd = QLCDNumber()
        right_lcd.setDigitCount(5)
        right_lcd.setStyleSheet("color: green; background-color: black;")
        right_lcd.setMinimumHeight(40)
        right_lcd.display(67890)
        
        self.right_button = QPushButton("OPEN")
        self.right_button.setMinimumHeight(32)
        
        right_subgroup_layout.addWidget(self.right_label)
        right_subgroup_layout.addWidget(right_lcd)
        right_subgroup_layout.addWidget(self.right_button)
        right_subgroup.setLayout(right_subgroup_layout)
        
        # Add subgroups to main group
        second_main_group_layout.addWidget(left_subgroup)
        second_main_group_layout.addWidget(right_subgroup)
        second_main_group.setLayout(second_main_group_layout)
        
        # Add components to second tab layout
        second_tab_layout.addWidget(red_rectangle)
        second_tab_layout.addWidget(second_main_group)
        
        second_tab.setLayout(second_tab_layout)

        # Third Tab
        third_tab = QWidget()
        third_tab_layout = QVBoxLayout()
        
       # Wavelength Control Group
        wavelength_group = QGroupBox("Wavelength Control")
        wavelength_layout = QVBoxLayout()
        
        # Wavelength Preset Buttons
        preset_layout = QHBoxLayout()
        preset_buttons = [
            ("680 nm", 680),
            ("700 nm", 700),
            ("750 nm", 750)
        ]
        
        for label, wavelength in preset_buttons:
            btn = QPushButton(label)
            btn.setMinimumHeight(40)
            btn.clicked.connect(lambda checked, wl=wavelength: self.set_wavelength(wl))
            preset_layout.addWidget(btn)
        
        # Manual Wavelength Input
        manual_input_layout = QHBoxLayout()
        manual_input_label = QLabel("Enter Wavelength:")
        manual_input = QLineEdit()
        manual_input.setPlaceholderText("Enter wavelength (nm)")
        manual_input.setValidator(QIntValidator(600, 800))  # Limit input to 600-800 nm
        
        set_manual_btn = QPushButton("Set")
        set_manual_btn.setMinimumHeight(32)
        
        # Connect manual input button
        def set_manual_wavelength():
            try:
                wavelength = int(manual_input.text())
                if 600 <= wavelength <= 800:
                    self.set_wavelength(wavelength)
                    manual_input.clear()
                else:
                    QMessageBox.warning(None, "Invalid Input", "Wavelength must be between 600-800 nm")
            except ValueError:
                QMessageBox.warning(None, "Invalid Input", "Please enter a valid number")
        
        set_manual_btn.clicked.connect(set_manual_wavelength)
        
        manual_input_layout.addWidget(manual_input_label)
        manual_input_layout.addWidget(manual_input)
        manual_input_layout.addWidget(set_manual_btn)
        
        # Current Wavelength Display
        wavelength_display = QLineEdit(f"{self.current_wavelength} nm")
        wavelength_display.setReadOnly(True)
        wavelength_display.setStyleSheet("""
            background-color: #f0f0f0;
            color: black;
            border: 1px solid #a0a0a0;
            padding: 4px;
            font-size: 16px;
            font-weight: bold;
        """)
        
        # Read-only Slider for Visualization
        slider_layout = QHBoxLayout()
        slider_label = QLabel("Wavelength Range:")
        wavelength_slider = QSlider(Qt.Horizontal)
        wavelength_slider.setMinimum(680)
        wavelength_slider.setMaximum(1030)
        wavelength_slider.setValue(self.current_wavelength)
        wavelength_slider.setEnabled(False)  # Make slider read-only
        
        slider_layout.addWidget(slider_label)
        slider_layout.addWidget(wavelength_slider)
        
        # Add components to wavelength layout
        wavelength_layout.addLayout(preset_layout)
        wavelength_layout.addLayout(manual_input_layout)
        wavelength_layout.addWidget(wavelength_display)
        wavelength_layout.addLayout(slider_layout)
        
        wavelength_group.setLayout(wavelength_layout)
        
        # Add wavelength group to third tab layout
        third_tab_layout.addWidget(wavelength_group)
        
        # Add stretch to push content to the top
        third_tab_layout.addStretch(1)
        
        third_tab.setLayout(third_tab_layout)
        
        # Add tabs to the tab widget
        tab_widget.addTab(first_tab, "State Info")
        tab_widget.addTab(second_tab, "Beam Control")
        tab_widget.addTab(third_tab, "Wavelength")
        
        # Create a main layout for the dock widget
        main_layout = QVBoxLayout()
        main_layout.addWidget(tab_widget)
        
        # Set the layout for the main widget
        main_widget.setLayout(main_layout)
        
        # Set the main widget for the dock
        dock.setWidget(main_widget)
        
        # Set allowed dock areas
        dock.setAllowedAreas(Qt.TopDockWidgetArea | Qt.BottomDockWidgetArea)
        
        # Add the dock to the parent widget
        parentWidget.addDockWidget(Qt.TopDockWidgetArea, dock)
        
        if menu:
            menu.addAction(dock.toggleViewAction())