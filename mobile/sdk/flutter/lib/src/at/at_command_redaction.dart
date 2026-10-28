/// Never include Wi-Fi passwords or device credentials in errors or logs.
String redactAtCommand(String command) {
  final value = command.trim();
  final upper = value.toUpperCase();
  if (upper.startsWith('AT+NETCFG=') || upper.startsWith('AT+UPLOADCFG=')) {
    return '${value.split('=').first}=<redacted>';
  }
  return value.length <= 48 ? value : '${value.substring(0, 48)}...';
}
