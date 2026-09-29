# Family Entries REST API — Plan Brief

> Full plan: `context/changes/family-entries-rest-api/plan.md`

## What & Why

Udostępnić automatyzacji rodzica odczyt wpisów jego rodziny przez REST API. Jest to świadome rozszerzenie uprawnień tokenu zapisane jako `MS-01`; API pozostaje wyłącznie do odczytu i nie może ujawnić danych innej rodziny.

## Starting Point

Projekt ma gotową autoryzację Bearer, walidację aktywnego tokenu rodzica, rodzinne filtrowanie wpisów oraz API oparte na zwykłych widokach Django. Brakuje endpointu kolekcji, kontraktu JSON, filtrów dat i paginacji.

## Desired End State

Aktywny token rodzica może pobierać wyłącznie wpisy rodziny właściciela. Klient może stronicować wyniki, ograniczać je włącznie traktowanym zakresem dat oraz opcjonalnie dołączać wpisy bez daty.

## Key Decisions Made

| Decyzja | Wybór | Uzasadnienie |
| --- | --- | --- |
| Endpoint | `GET /api/automation/entries/` | Realizuje wymagany odczyt bez poszerzania API o szczegóły lub mutacje |
| Paginacja | `limit + offset` | Prosta obsługa przez `curl` |
| Limity | domyślnie 100, maksimum 500 | Chroni serwer przed nieograniczoną odpowiedzią |
| Kolejność | `created_at ASC, id ASC` | Stabilna kolejność; nowe wpisy nie przesuwają wcześniejszych stron offsetowych |
| Filtry | `date_from`, `date_to`, `include_undated` | Obsługuje typowy zakres od dziś do +4 tygodni |
| Rekord | pełne pola domenowe | Daje użyteczny kontrakt bez ujawniania pól wewnętrznych |
| Przypisana osoba | nazwa albo `null` | Nie wymaga osobnego API członków rodziny |
| Technologia | zwykły widok Django | Zachowuje istniejący wzorzec bez wprowadzania DRF |

## Scope

**In scope:** kolekcja wpisów, filtry dat, paginacja, serializacja, autoryzacja tokenowa, izolacja rodziny, testy i dokumentacja `curl`.

**Out of scope:** endpoint pojedynczego wpisu, mutacje, filtrowanie po osobie lub rodzaju, API członków rodziny, nowe scope’y tokenów, UI i migracje bazy.

## Architecture / Approach

Widok API ponownie używa `automation_token_required`. Rodzina pochodzi wyłącznie z uwierzytelnionego `request.automation_membership`; rodzinny queryset stosuje filtry i stabilne sortowanie, a jawny serializer buduje bezpieczny kontrakt JSON.

## Phases at a Glance

| Faza | Rezultat | Główne ryzyko |
| --- | --- | --- |
| 1. Kontrakt odczytu | Walidacja parametrów, filtrowanie i serializacja | Niejednoznaczny zakres dat |
| 2. Endpoint i bezpieczeństwo | Działający GET z pełną izolacją rodziny | Wyciek danych między rodzinami |
| 3. Dokumentacja i akceptacja | Przykłady `curl` i pełna regresja | Rozbieżność dokumentacji z API |

**Prerequisites:** ukończone F-04 i S-01; istniejący model `Entry` i tokeny automatyzacji.

**Estimated effort:** około 1–2 sesji implementacyjnych w trzech fazach.

## Open Risks & Assumptions

- `MS-01` celowo zastępuje wyłącznie wcześniejszy zakaz odczytu przez token; nie zezwala na mutacje ani inne dane rodziny.
- Niski wolumen rodzinny pozwala użyć `count` oraz paginacji offsetowej bez nowego indeksu; indeks należy dodać dopiero na podstawie pomiaru.
- Nieaktywna historyczna osoba nadal może być pokazana przez `display_name`, ponieważ wpis zachowuje przypisanie.

## Success Criteria (Summary)

- Token rodzica pobiera wyłącznie wpisy swojej rodziny, a nieważny lub cofnięty token natychmiast otrzymuje 401.
- Filtry dat, `include_undated`, kolejność i paginacja zachowują udokumentowany kontrakt.
- Żadna metoda API nie umożliwia zmiany wpisów, a odpowiedź nie ujawnia pól wewnętrznych.
