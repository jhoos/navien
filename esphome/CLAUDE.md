# ESPHome API Reference for Claude

This document contains a quick reference for the ESPHome API to help understand and develop custom components.

## Key Documentation Sources

### Primary Resources
- **Developer Docs - Components**: https://developers.esphome.io/architecture/components/
  - Component architecture, lifecycle, setup priorities
- **Component API Reference**: https://esphome.io/api/classesphome_1_1_component
- **GitHub Source**: https://github.com/esphome/esphome/blob/dev/esphome/
  - Header files for detailed class definitions

### Component-Specific Docs
- **Climate**: https://esphome.io/components/climate/index.html
  - GitHub: `esphome/components/climate/climate.h`
- **Sensor**: https://esphome.io/components/sensor/
  - GitHub: `esphome/components/sensor/sensor.h`
- **Binary Sensor**: https://esphome.io/components/binary_sensor/index.html
- **Switch**: https://esphome.io/components/switch/
- **UART**: https://esphome.io/components/uart/
  - GitHub: `esphome/components/uart/uart.h`

## Component Base Classes

### Component
Core base class with lifecycle methods:

```cpp
class Component {
  virtual void setup();           // One-time initialization
  virtual void loop();            // Called ~every 7ms, must be non-blocking
  virtual void dump_config();     // Display configuration
  virtual float get_setup_priority() const;  // Return setup priority

  // Shutdown methods (optional)
  virtual void on_shutdown();
  virtual void on_safe_shutdown();
  virtual bool teardown();
  virtual void on_powerdown();
};
```

**Key points:**
- All methods must be non-blocking
- `loop()` runs continuously at ~7ms intervals
- Override `get_setup_priority()` to control initialization order

### PollingComponent
Extends Component with periodic updates:

```cpp
class PollingComponent : public Component {
  virtual void update() = 0;      // Called at update_interval
  void set_update_interval(uint32_t update_interval);
  uint32_t get_update_interval();
};
```

**Usage:** Ideal for sensors that need periodic polling

## Setup Priorities

Higher values initialize first (execution order):

```cpp
namespace setup_priority {
  const float BUS = 1000.0f;              // I2C, SPI buses
  const float IO = 900.0f;                // GPIO pins
  const float HARDWARE = 800.0f;          // Hardware components
  const float DATA = 600.0f;              // Direct sensor connections
  const float PROCESSOR = 400.0f;         // Components using sensor data
  const float BLUETOOTH = 350.0f;
  const float AFTER_BLUETOOTH = 300.0f;
  const float WIFI = 250.0f;
  const float ETHERNET = 250.0f;
  const float BEFORE_CONNECTION = 220.0f;
  const float AFTER_WIFI = 200.0f;
  const float AFTER_CONNECTION = 100.0f;
  const float LATE = -100.0f;             // Final initialization
}
```

**Common usage:**
- HARDWARE: For GPIO switches, UART devices
- DATA: For sensors reading from hardware
- PROCESSOR: For displays using sensor data

## UART Communication

### UARTDevice Class

```cpp
class UARTDevice {
  // Configuration
  void set_uart_parent(UARTComponent *parent);

  // Read methods
  int available();                              // Bytes available
  bool read_byte(uint8_t *data);               // Read single byte
  bool peek_byte(uint8_t *data);               // Peek without consuming
  bool read_array(uint8_t *data, size_t len); // Read multiple bytes

  // Write methods
  void write_byte(uint8_t data);
  void write_array(const uint8_t *data, size_t len);
  void write_array(const std::vector<uint8_t> &data);
  void write_str(const char *str);

  // Utility
  void flush();                                 // Clear buffers
};
```

**Typical usage:**
```cpp
class MyComponent : public PollingComponent, public uart::UARTDevice {
  void loop() override {
    while (available()) {
      uint8_t byte;
      read_byte(&byte);
      // Process byte
    }
  }
};
```

## Sensor Component

```cpp
class Sensor : public EntityBase {
  // State members
  float state;          // Filtered value (NAN if no data)
  float raw_state;      // Unfiltered value

  // Methods
  void publish_state(float state);     // Push new value through filters
  float get_state();                   // Get current filtered state
  float get_raw_state();               // Get unfiltered state
  bool has_state();                    // Check if state is valid (!NAN)

  // Configuration
  void set_accuracy_decimals(int8_t decimals);
  void set_state_class(StateClass state_class);
  void add_filter(Filter *filter);
};
```

**Usage:**
```cpp
if (my_sensor != nullptr) {
  my_sensor->publish_state(temperature_value);
}
```

## Binary Sensor Component

```cpp
class BinarySensor : public EntityBase {
  bool state;  // Current state

  void publish_state(bool state);  // Publish true/false state
};
```

**Usage:**
```cpp
if (conn_status_sensor != nullptr) {
  conn_status_sensor->publish_state(is_connected);
}
```

## Switch Component

```cpp
class Switch : public EntityBase {
  bool state;  // Current state

  // Override this to implement custom switch
  virtual void write_state(bool state) = 0;

  // Publishing (don't call write_state, just update frontend)
  void publish_state(bool state);

  // User control (calls write_state)
  void turn_on();
  void turn_off();
  void toggle();
};
```

**Implementation pattern:**
```cpp
class MySwitch : public switch_::Switch {
  void write_state(bool state) override {
    // Actually control hardware here
    if (state) {
      parent->send_turn_on_cmd();
    } else {
      parent->send_turn_off_cmd();
    }
    // Update frontend
    publish_state(state);
  }
};
```

**Important:** `publish_state()` only notifies frontend, doesn't control hardware

## Climate Component

### Climate Class

```cpp
class Climate : public EntityBase {
  // State properties (read/write)
  float current_temperature = NAN;
  float current_humidity = NAN;
  float target_temperature = NAN;
  float target_temperature_low = NAN;
  float target_temperature_high = NAN;
  float target_humidity = NAN;
  ClimateMode mode;
  ClimateAction action;
  ClimateFanMode fan_mode;
  ClimateSwingMode swing_mode;
  optional<std::string> preset;
  optional<std::string> custom_fan_mode;
  optional<std::string> custom_preset;

  // Methods to implement
  virtual ClimateTraits traits() = 0;
  virtual void control(const ClimateCall &call) = 0;

  // State management
  void publish_state();              // Broadcast state to listeners
  ClimateCall make_call();           // Create control request
};
```

### ClimateTraits

Defines device capabilities:

```cpp
class ClimateTraits {
  // Supported modes
  void set_supported_modes(std::set<ClimateMode> modes);
  void add_supported_mode(ClimateMode mode);

  // Temperature ranges
  void set_visual_min_temperature(float temp);
  void set_visual_max_temperature(float temp);
  void set_visual_temperature_step(float step);
  void set_visual_current_temperature_step(float step);

  // Features
  void set_supports_current_temperature(bool support);
  void set_supports_two_point_target_temperature(bool support);
  void set_supports_action(bool support);

  // Fan modes
  void set_supported_fan_modes(std::set<ClimateFanMode> modes);
  void add_supported_custom_fan_mode(const std::string &mode);

  // Presets
  void add_supported_preset(ClimatePreset preset);
  void add_supported_custom_preset(const std::string &preset);
};
```

### ClimateCall

Control request builder:

```cpp
class ClimateCall {
  // Getters (return optional<T>)
  optional<ClimateMode> get_mode();
  optional<float> get_target_temperature();
  optional<float> get_target_temperature_low();
  optional<float> get_target_temperature_high();
  optional<ClimateFanMode> get_fan_mode();
  optional<ClimatePreset> get_preset();

  // Setters
  ClimateCall& set_mode(ClimateMode mode);
  ClimateCall& set_target_temperature(float temp);
  ClimateCall& set_fan_mode(ClimateFanMode mode);

  void perform();  // Execute the call
};
```

### Climate Implementation Pattern

```cpp
class MyClimate : public climate::Climate, public Component {
public:
  ClimateTraits traits() override {
    auto traits = climate::ClimateTraits();
    traits.set_supported_modes({
      climate::CLIMATE_MODE_OFF,
      climate::CLIMATE_MODE_HEAT
    });
    traits.set_supports_current_temperature(true);
    traits.set_visual_min_temperature(37.0f);
    traits.set_visual_max_temperature(60.0f);
    traits.set_visual_temperature_step(1.0f);
    return traits;
  }

  void control(const ClimateCall &call) override {
    if (call.get_mode().has_value()) {
      this->mode = *call.get_mode();
    }
    if (call.get_target_temperature().has_value()) {
      this->target_temperature = *call.get_target_temperature();
      // Send command to hardware
      parent->send_set_temp_cmd(this->target_temperature);
    }
    // Update all listeners
    this->publish_state();
  }
};
```

## Common Patterns

### Multiple Inheritance Pattern
```cpp
class Navien : public PollingComponent, public uart::UARTDevice {
  float get_setup_priority() const override {
    return setup_priority::HARDWARE;
  }
};
```

### Optional Sensor Pattern
```cpp
void update_sensors() {
  if (temperature_sensor != nullptr) {
    temperature_sensor->publish_state(current_temp);
  }
  if (pressure_sensor != nullptr) {
    pressure_sensor->publish_state(current_pressure);
  }
}
```

### Parent Component Pattern
```cpp
class ChildComponent : public Component {
  ParentComponent *parent = nullptr;

  void set_parent(ParentComponent *p) { parent = p; }

  void do_something() {
    if (parent != nullptr) {
      parent->some_method();
    }
  }
};
```

## Important Notes

1. **Non-blocking code**: All `loop()`, `update()`, and `setup()` methods must not block
2. **Null checks**: Always check if optional sensors/switches are nullptr before using
3. **State publishing order**: Set properties first, then call `publish_state()`
4. **Setup priority**: Higher values run first (shutdown is reverse order)
5. **Climate flow**: User calls `control()` → update properties → call `publish_state()`
6. **Switch distinction**: `write_state()` controls hardware, `publish_state()` only updates UI

## 2025 Breaking Changes

Starting with ESPHome 2025.10.0:
- All action/trigger/condition method signatures use `const` references instead of pass-by-value
- Custom components moving to external components (encouraged but not required yet)
- Remove support blog post: https://developers.esphome.io/blog/2025/02/19/about-the-removal-of-support-for-custom-components/

## Quick Search Tips

When looking up API details:
1. Start with user docs: https://esphome.io/components/
2. Check developer docs: https://developers.esphome.io/
3. Look at source headers on GitHub for exact signatures
4. API reference (if URLs work): https://esphome.io/api/
5. Search for real examples in the esphome/esphome GitHub repo
