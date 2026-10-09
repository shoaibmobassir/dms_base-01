"""Legal research benchmark questions, in the shape of Legal Research Bench (Vals AI, COLM 2026, arXiv:2610.00609).

Each question has a gold answer and a binary rubric with weights +1/+2/+3 (at least one +3 carries the central
conclusion). A response is **correct only if every rubric item passes AND the source check passes** (every
authority it cites from the firm's collections resolves and its pinpoint exists): the paper's "all-pass" metric.

Rubric item kinds:
  judge   an LLM judge decides from the response alone
  cites   the response cites one of ``any`` (or all of ``all``) as a parseable citation key

Attributes mirror the paper's difficulty marks: ``reconciliation`` (several authorities must be synthesized) and
``temporal`` (the answer depends on a date). ``source_check`` is off where the question itself contains the
citations under test.

Gold answers rest on the corpus text and the verified facts in docs/experiments/lrb_style_benchmark_2026-10-02.md.
"""
from __future__ import annotations

AS_OF = "Answer as of 2 October 2026."


def J(w: int, text: str) -> dict:
    return {"kind": "judge", "w": w, "text": text}


def C(w: int, *keys: str, text: str = "", all_of: bool = False) -> dict:
    return {"kind": "cites", "w": w, "keys": list(keys), "all": all_of, "text": text or "Cites " + (" and " if all_of else " or ").join(keys)}


QUESTIONS: list[dict] = [
    # ---------------- doctrinal rule reasoning (PCIJ) ----------------
    dict(id="D01", scenario="doctrinal", attrs=[], question=(
        "State A's warship collides on the high seas with a merchant vessel flying State B's flag. State B's courts "
        "prosecute the officer of the watch of A's warship. State A argues that international law forbids B from "
        "exercising criminal jurisdiction over a foreign officer for an incident on the high seas. Is A right? "
        "Identify the controlling authority and the reasoning."),
        gold="No. In the Lotus case (PCIJ, Series A No. 10) the Court held that international law does not prohibit a State from exercising criminal jurisdiction in such a case: restrictions upon the independence of States cannot be presumed, so a prohibition must be shown; the effects of the offence were produced on a vessel flying the other State's flag, which is assimilated to its territory. PCIJ decisions bind only the parties; they are persuasive elsewhere.",
        rubric=[J(3, "Concludes that State A is wrong: international law does not prohibit State B from exercising criminal jurisdiction here."),
                J(2, "States that restrictions upon the independence of States cannot be presumed (a prohibition must be shown to exist)."),
                J(2, "Explains that the effects of the offence were produced on the vessel flying B's flag, which is assimilated to B's territory."),
                C(3, "pcij:A:10", text="Cites the Lotus judgment (P.C.I.J., Series A, No. 10)."),
                J(1, "Notes that the Court's decision is not binding precedent for other cases (persuasive authority).")]),
    dict(id="D02", scenario="doctrinal", attrs=[], question=(
        "Two States disagree over whether one of them may bring a claim against the other on behalf of its national. "
        "What does a 'dispute' require in international law, and in whose right does a State act when it takes up "
        "its national's case?"),
        gold="Mavrommatis Palestine Concessions (PCIJ, Series A No. 2): a dispute is a disagreement on a point of law or fact, a conflict of legal views or of interests between two persons. By taking up the case of its subject a State is in reality asserting its own right, to ensure respect for international law in the person of its subject. The decision binds only the parties; for others it is persuasive authority, not binding precedent.",
        rubric=[J(3, "Defines a dispute as a disagreement on a point of law or fact, a conflict of legal views or of interests between parties."),
                J(3, "States that a State taking up its national's case asserts its own right (to ensure respect for international law in the person of its subject)."),
                C(3, "pcij:A:2", text="Cites Mavrommatis (P.C.I.J., Series A, No. 2)."),
                J(1, "Notes that the Court's decision is not binding precedent for other cases (persuasive authority).")]),
    dict(id="D03", scenario="doctrinal", attrs=[], question=(
        "A State has expropriated a factory in breach of a treaty. What form must reparation take, and what is the "
        "governing standard?"),
        gold="Chorzow Factory (PCIJ, Series A No. 17; and No. 9 for the principle that breach of an engagement involves an obligation to make reparation): reparation must, as far as possible, wipe out all the consequences of the illegal act and re-establish the situation which would, in all probability, have existed if the act had not been committed. Restitution in kind or, if impossible, payment of a sum corresponding to the value of restitution; plus damages for loss sustained which restitution or its equivalent would not cover.",
        rubric=[J(3, "States the standard: reparation must, as far as possible, wipe out all the consequences of the illegal act and re-establish the situation that would probably have existed."),
                J(3, "Identifies restitution in kind or, if that is impossible, payment of a sum corresponding to its value."),
                J(2, "Adds damages for loss sustained that restitution or its equivalent would not cover."),
                C(3, "pcij:A:17", "pcij:A:9", text="Cites Chorzow Factory (Series A No. 17 or No. 9).")]),
    dict(id="D04", scenario="doctrinal", attrs=[], question=(
        "Asked by another State's diplomatic representative about its plans to extend sovereignty over a territory, a "
        "foreign minister replies orally that his government will not make any difficulty. Is his State bound by "
        "that reply?"),
        gold="Yes. Legal Status of Eastern Greenland (PCIJ, Series A/B No. 53): the Ihlen declaration, an oral reply by the Foreign Minister on behalf of his government to a request by a foreign diplomatic representative on a matter within his province, is binding on the country to which he belongs; Norway was under an obligation not to contest Danish sovereignty.",
        rubric=[J(3, "Concludes that the State is bound by the foreign minister's oral reply."),
                J(2, "Grounds this in the reply being given on behalf of his government, to a request by a foreign diplomatic representative, on a matter within his province."),
                C(3, "pcij:A/B:53", text="Cites Eastern Greenland (P.C.I.J., Series A/B, No. 53)."),
                J(1, "Draws the consequence that the State must refrain from contesting the other State's position.")]),
    dict(id="D05", scenario="doctrinal", attrs=[], question=(
        "Under minority-protection treaties, is formal legal equality between minority and majority schools enough?"),
        gold="No. Minority Schools in Albania (PCIJ, Series A/B No. 64): equality in law precludes discrimination of any kind, but equality in fact is also required, so that minorities can preserve their institutions. The decision is persuasive authority, not binding precedent, for other cases.",
        rubric=[J(3, "Concludes that formal equality in law is not enough: equality in fact is also required."),
                C(3, "pcij:A/B:64", text="Cites Minority Schools in Albania (P.C.I.J., Series A/B, No. 64)."),
                J(1, "Notes that the Court's decision is not binding precedent for other cases (persuasive authority).")]),
    dict(id="D06", scenario="doctrinal", attrs=[], question=(
        "Can a State rely on the provisions of its own constitution to escape its international obligations towards "
        "another State?"),
        gold="No. Treatment of Polish Nationals in Danzig (PCIJ, Series A/B No. 44): a State cannot adduce against another State its own constitution to evade obligations incumbent upon it under international law or treaties in force. The decision is persuasive authority, not binding precedent, for other cases.",
        rubric=[J(3, "Concludes that a State cannot invoke its own constitution against another State to avoid international obligations."),
                C(3, "pcij:A/B:44", text="Cites Treatment of Polish Nationals in Danzig (P.C.I.J., Series A/B, No. 44)."),
                J(1, "Notes that the Court's decision is not binding precedent for other cases (persuasive authority).")]),
    dict(id="D07", scenario="doctrinal", attrs=[], question=(
        "Is a proposed customs union between two States compatible with one of them having undertaken not to alienate "
        "its independence? Also, are the Permanent Court's advisory opinions binding?"),
        gold="Customs Regime between Germany and Austria (PCIJ, Series A/B No. 41): the Court answered, by a narrow majority, that the proposed regime would be incompatible with Austria's undertaking in Protocol No. I of Geneva (1922) not to alienate its independence. Advisory opinions are not binding, though they carry great weight.",
        rubric=[J(3, "States that the proposed regime was held incompatible with Austria's 1922 Protocol undertaking not to alienate its independence."),
                J(2, "States that advisory opinions are not binding (though weighty)."),
                C(3, "pcij:A/B:41", text="Cites the Customs Regime advisory opinion (P.C.I.J., Series A/B, No. 41).")]),
    dict(id="D08", scenario="doctrinal", attrs=[], question=(
        "When is a matter 'solely within the domestic jurisdiction' of a State, so that international law does not "
        "regulate it? Give the Permanent Court's approach."),
        gold="Nationality Decrees in Tunis and Morocco (PCIJ, Series B No. 4, advisory opinion): whether a matter is solely within domestic jurisdiction is an essentially relative question; it depends on the development of international relations, and a matter that is in principle domestic may be restricted by obligations to other States (for example by treaty).",
        rubric=[J(3, "Explains that it is not a fixed category: it depends on the development of international relations."),
                J(2, "Adds that a matter in principle domestic can be limited by international obligations such as treaties."),
                C(3, "pcij:B:4", text="Cites Nationality Decrees (P.C.I.J., Series B, No. 4).")]),
    # ---------------- statutory interpretation (UN Security Council) ----------------
    dict(id="S01", scenario="statutory", attrs=[], question=(
        "Is every State obliged to freeze the funds of persons who commit or attempt terrorist acts? State the source "
        "and its binding force, and distinguish obligations from mere exhortations in the same text."),
        gold="Yes. S/RES/1373 (2001), para. 1(c), decides that all States shall freeze without delay funds of persons who commit or attempt terrorist acts. It was adopted acting under Chapter VII, so it binds Member States (Charter Art. 25). Paragraph 3 only 'calls upon' States, which is recommendatory.",
        rubric=[J(3, "Concludes that all States are obliged to freeze such funds, citing paragraph 1 of resolution 1373 (2001)."),
                J(3, "Explains the obligation is binding because the resolution is a decision adopted under Chapter VII (Charter Art. 25)."),
                J(2, "Distinguishes operative language that merely 'calls upon' States (such as paragraph 3) as not creating an obligation."),
                C(3, "unsc:1373", text="Cites S/RES/1373 (2001).")]),
    dict(id="S02", scenario="statutory", attrs=[], question=(
        "Did the Security Council in 1990 oblige Member States to use force against Iraq?"),
        gold="No. S/RES/678 (1990), para. 2, authorizes Member States co-operating with Kuwait, unless Iraq fully implemented the earlier resolutions by 15 January 1991, to use all necessary means; it is permissive, not an obligation. Adopted under Chapter VII.",
        rubric=[J(3, "Concludes that the resolution authorized, but did not oblige, Member States to use force."),
                J(2, "States that the authorization applied to States co-operating with Kuwait, unless Iraq complied by 15 January 1991."),
                J(2, "Notes the resolution was adopted under Chapter VII."),
                C(3, "unsc:678", text="Cites S/RES/678 (1990).")]),
    dict(id="S03", scenario="statutory", attrs=[], question=(
        "Is Sudan obliged to cooperate with the International Criminal Court in the Darfur situation, and what is the "
        "position of States that are not party to the Rome Statute?"),
        gold="S/RES/1593 (2005) decides to refer the situation in Darfur to the ICC Prosecutor and decides that the Government of Sudan and all parties to the conflict shall cooperate fully with the Court (binding, Chapter VII). States not party to the Rome Statute have no obligation under it; the resolution only urges all States to cooperate fully.",
        rubric=[J(3, "States that Sudan and the other parties to the conflict are obliged to cooperate, by a decision in resolution 1593 (2005)."),
                J(3, "States that other States, not party to the Rome Statute, are only urged to cooperate (no obligation under the resolution)."),
                C(3, "unsc:1593", text="Cites S/RES/1593 (2005).")]),
    dict(id="S04", scenario="statutory", attrs=[], question=(
        "Must States prevent non-State actors from acquiring nuclear, chemical or biological weapons? What exactly "
        "does the Security Council require?"),
        gold="Yes. S/RES/1540 (2004) decides that all States shall refrain from providing any form of support to non-State actors that attempt to develop, acquire or use such weapons, shall adopt and enforce effective laws prohibiting them, and shall establish domestic controls. Adopted under Chapter VII.",
        rubric=[J(3, "States that all States must refrain from supporting non-State actors seeking such weapons."),
                J(3, "States that States must adopt and enforce effective laws and establish domestic controls."),
                J(2, "Notes this is a binding decision under Chapter VII."),
                C(3, "unsc:1540", text="Cites S/RES/1540 (2004).")]),
    # ---------------- temporal validity ----------------
    dict(id="T01", scenario="temporal", attrs=["temporal"], question=AS_OF + " Is the UN Mission to Support the Hodeidah Agreement (UNMHA) still mandated by the Security Council?",
        gold="No. S/RES/2813 (2026) was a final extension of the mandate until 31 March 2026 for drawdown, after which the mission was to be liquidated. The previous extension, S/RES/2786 (2025), ran to 28 January 2026.",
        rubric=[J(3, "Concludes the mandate has ended (it is no longer mandated as of 2 October 2026)."),
                J(3, "States that resolution 2813 (2026) was a final extension until 31 March 2026."),
                C(3, "unsc:2813", text="Cites S/RES/2813 (2026)."),
                J(1, "Mentions that the previous extension (resolution 2786 (2025)) ran to 28 January 2026.")]),
    dict(id="T02", scenario="temporal", attrs=["temporal"], question=AS_OF + " Until what date has the Security Council extended the authorisation of the African Union Support and Stabilisation Mission in Somalia (AUSSOM), and in which resolution?",
        gold="Until 31 December 2026, in S/RES/2809 (2025), adopted 23 December 2025.",
        rubric=[J(3, "States the authorisation runs until 31 December 2026."),
                C(3, "unsc:2809", text="Cites S/RES/2809 (2025).")]),
    dict(id="T03", scenario="temporal", attrs=["temporal", "reconciliation"], question=AS_OF + " Until what dates are the mandates of the UN Peacekeeping Force in Cyprus (UNFICYP) and of the UN Integrated Office in Haiti (BINUH) extended?",
        gold="Both run until 31 January 2027: UNFICYP under S/RES/2815 (2026) and BINUH under S/RES/2814 (2026).",
        rubric=[J(3, "States UNFICYP's mandate runs until 31 January 2027."),
                J(3, "States BINUH's mandate runs until 31 January 2027."),
                C(3, "unsc:2815", "unsc:2814", all_of=True, text="Cites S/RES/2815 (2026) and S/RES/2814 (2026).")]),
    dict(id="T04", scenario="temporal", attrs=["temporal"], question="Answer as of 1 January 2026. Was the mandate of the UN Mission to Support the Hodeidah Agreement (UNMHA) in force, and until when?",
        gold="Yes. On 1 January 2026 UNMHA's mandate was in force under S/RES/2786 (2025), which extended it until 28 January 2026. (The later final extension in S/RES/2813 (2026) came after that date.)",
        rubric=[J(3, "States that the mandate was in force on 1 January 2026 and ran until 28 January 2026."),
                C(3, "unsc:2786", text="Cites S/RES/2786 (2025)."),
                J(2, "Does not say the mandate had already ended on 1 January 2026.")]),
    dict(id="T05", scenario="temporal", attrs=["temporal", "reconciliation"], question=AS_OF + " Trace each Security Council extension of UNMHA's mandate from 2023 until the mission's end, giving the resolution, its date and the new expiry.",
        gold="S/RES/2691 (10 July 2023): until 14 July 2024. S/RES/2742 (8 July 2024): until 14 July 2025. S/RES/2786 (14 July 2025): until 28 January 2026. S/RES/2813 (27 January 2026): final extension until 31 March 2026, with liquidation after.",
        rubric=[J(2, "Resolution 2691 (2023) extended the mandate until 14 July 2024."),
                J(2, "Resolution 2742 (2024) extended the mandate until 14 July 2025."),
                J(2, "Resolution 2786 (2025) extended the mandate until 28 January 2026."),
                J(3, "Resolution 2813 (2026) was the final extension, until 31 March 2026."),
                C(2, "unsc:2691", "unsc:2742", "unsc:2786", "unsc:2813", all_of=True, text="Cites all four resolutions.")]),
    # ---------------- reconciliation ----------------
    dict(id="R01", scenario="reconciliation", attrs=["reconciliation"], question=(
        "One State argues that any treaty undertaking restricting its freedom of action is invalid as an infringement "
        "of its sovereignty. Another argues that restrictions upon the independence of States can never be presumed. "
        "Reconcile what the Permanent Court said on these two points."),
        gold="Wimbledon (Series A No. 1): the right of entering into international engagements is an attribute of State sovereignty, so a treaty restricting the exercise of sovereign rights is not an infringement of it. Lotus (Series A No. 10): restrictions upon independence cannot be presumed. They fit together: limits on a State come from its consent or an established rule, not from presumption; and consenting to limits is itself an exercise of sovereignty.",
        rubric=[J(3, "States the Wimbledon point: entering into international engagements is an attribute of sovereignty, not an abandonment of it."),
                J(3, "States the Lotus point: restrictions upon the independence of States cannot be presumed."),
                J(2, "Reconciles them: limits arise from consent or an established rule, and accepting a treaty limit is itself an exercise of sovereignty."),
                C(3, "pcij:A:1", "pcij:A:10", all_of=True, text="Cites both Wimbledon (Series A No. 1) and Lotus (Series A No. 10).")]),
    # ---------------- integrity: abstention, false premises, cite-check ----------------
    dict(id="I01", scenario="abstain", attrs=[], source_check=False, question=(
        "Under the Electricity Act 2003, within what period must an appeal against an order of the Central "
        "Electricity Regulatory Commission be filed before the Appellate Tribunal for Electricity, and which "
        "Supreme Court judgment settles how that period is computed? Give citations."),
        gold="The firm's research collection holds no Indian statutes or judgments. A correct response says so, does not cite an Indian judgment as verified, and flags anything it states from general knowledge as unverified.",
        rubric=[J(3, "States that Indian statutes or judgments are not in the available research collection, or that the answer could not be verified with the available sources."),
                J(3, "Does not present a specific Supreme Court judgment or reporter citation as a verified authority (any such citation is clearly marked unverified or omitted).")]),
    dict(id="I02", scenario="abstain", attrs=[], source_check=False, question=(
        "What did the International Court of Justice hold on the non-use of force in Nicaragua v. United States (1986)? "
        "Give the I.C.J. Reports citation."),
        gold="The ICJ's judgments are not in the firm's research collection (only PCIJ decisions and Security Council resolutions). A correct response says it cannot verify the ICJ judgment from the available sources and does not present an ICJ Reports citation as verified.",
        rubric=[J(3, "States that ICJ judgments are not in the available collection or that the holding/citation could not be verified."),
                J(3, "Does not present an I.C.J. Reports citation as verified.")]),
    dict(id="I03", scenario="premise", attrs=[], question=(
        "In the Lotus case the Permanent Court held that States may never exercise criminal jurisdiction over foreign "
        "ships on the high seas. Summarise how the Court reached that result."),
        gold="The premise is false: the Court held the opposite. It found no rule of international law prohibiting Turkey from prosecuting; restrictions on independence cannot be presumed.",
        rubric=[J(3, "Corrects the premise: the Court did not hold that; it held that international law did not prohibit the exercise of jurisdiction."),
                C(3, "pcij:A:10", text="Cites the Lotus judgment (P.C.I.J., Series A, No. 10).")]),
    dict(id="I04", scenario="premise", attrs=[], source_check=False, question="Summarise what Security Council resolution 9876 (2031) decided.",
        gold="There is no such resolution; the response must say so and not describe any contents.",
        rubric=[J(3, "States that no such resolution exists or can be found in the collection."),
                J(3, "Does not describe any decision or content for resolution 9876 (2031) as if it existed.")]),
    dict(id="I05", scenario="premise", attrs=[], source_check=False, question="What did S/RES/1373 (2003) decide about the financing of terrorism?",
        gold="Resolution 1373 was adopted in 2001, not 2003. It decides that all States shall prevent and suppress terrorist financing and freeze funds.",
        rubric=[J(3, "Points out that resolution 1373 was adopted in 2001 and that there is no resolution 1373 (2003)."),
                J(3, "States that the resolution decides all States shall prevent and suppress financing of terrorist acts and freeze related funds."),
                C(3, "unsc:1373", text="Cites S/RES/1373 (2001).")]),
    dict(id="I06", scenario="citecheck", attrs=[], source_check=False, question=(
        "Cite-check the following paragraph and tell me which citations are wrong or cannot be verified: "
        "'The Security Council required all States to freeze terrorist assets (S/RES/1373 (2001), para. 1). It "
        "repeated this requirement in S/RES/1373 (2003), para. 1. The Lotus principle is stated at P.C.I.J., "
        "Series A, No. 10, p. 900. The Court's judgment in Series A, No. 40 on Mavrommatis confirms it. See also "
        "(2008) 4 SCC 755.'"),
        gold="(1) S/RES/1373 (2001), para. 1: correct. (2) S/RES/1373 (2003): no such resolution; 1373 was adopted in 2001. (3) Series A No. 10, p. 900: beyond the length of the decision; pinpoint invalid. (4) Series A No. 40: no such Series A judgment; Mavrommatis is Series A No. 2. (5) (2008) 4 SCC 755: an Indian report citation that cannot be verified with the available sources.",
        rubric=[J(2, "Confirms that S/RES/1373 (2001), para. 1 is a correct citation for the freezing requirement."),
                J(3, "Identifies that S/RES/1373 (2003) does not exist (resolution 1373 was adopted in 2001)."),
                J(3, "Identifies that page 900 of Series A No. 10 is not a valid pinpoint (beyond the decision's length)."),
                J(3, "Identifies that 'Series A, No. 40' is not Mavrommatis / does not exist (Mavrommatis is Series A No. 2)."),
                J(2, "States that the (2008) 4 SCC 755 citation cannot be verified with the available sources (does not call it verified).")]),
]

ALL_IDS = [q["id"] for q in QUESTIONS]
