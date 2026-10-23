import 'package:flutter/services.dart';
import 'tafsir.dart';

enum PersonalFailure { storage, unsupportedVersion, invalidData, unavailable }

class PersonalException implements Exception {
  const PersonalException(this.reason);
  final PersonalFailure reason;
}

/// Sole personal-store bridge. Queue spans route instances so a reopened route
/// reads after already requested writes, including writes from disposed routes.
/// Native database owns versioning, transactions and actual durable success.
class PersonalStore {
  const PersonalStore();
  static const channel = MethodChannel('quranly/personal');
  static Future<void>? _tail;

  Future<T> _serialized<T>(Future<T> Function() operation) {
    final pending = _tail == null
        ? operation()
        : _tail!.then((_) => operation());
    late final Future<void> queued;
    void finished() {
      if (identical(_tail, queued)) _tail = null;
    }

    queued = pending.then<void>(
      (_) => finished(),
      onError: (Object error, StackTrace stack) => finished(),
    );
    _tail = queued;
    return pending;
  }

  Future<Object?> _invoke(String method, [Object? arguments]) async {
    try {
      // Validate the transport value at the owning read boundary. A generic
      // channel cast would let malformed saved data escape as an untyped error.
      return await channel.invokeMethod<Object?>(method, arguments);
    } on PlatformException catch (error) {
      throw PersonalException(
        PersonalFailure.values.firstWhere(
          (value) => value.name == error.code,
          orElse: () => PersonalFailure.unavailable,
        ),
      );
    } on MissingPluginException {
      throw const PersonalException(PersonalFailure.unavailable);
    }
  }

  Future<TafsirBook> readTafsirBook() => _serialized(() async {
    final id = await _invoke('readTafsirBook');
    final book = TafsirBook.fromId(id);
    if (book == null) {
      throw const PersonalException(PersonalFailure.invalidData);
    }
    return book;
  });

  Future<void> writeTafsirBook(TafsirBook book) => _serialized(() async {
    await _invoke('writeTafsirBook', {'book': book.id});
  });
}
