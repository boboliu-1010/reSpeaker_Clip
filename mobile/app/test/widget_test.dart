import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:respeaker_app/src/app/app.dart';
import 'package:respeaker_app/src/core/legal/privacy_policy_gate.dart';
import 'package:respeaker_app/src/features/auth/presentation/login_landing_page.dart';

void main() {
  testWidgets('Signed-out app boots inside its provider and routes to login',
      (WidgetTester tester) async {
    SharedPreferences.setMockInitialValues({});
    await tester.pumpWidget(const ProviderScope(child: ReSpeakerApp()));
    await tester.pumpAndSettle();
    expect(find.byType(MaterialApp), findsOneWidget);
    expect(find.byType(PrivacyPolicyGate), findsOneWidget);
    expect(find.byType(LoginLandingPage), findsOneWidget);
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox.shrink());
  });
}
