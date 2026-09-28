"""Deterministic, parameterized core-Lean lemma catalogue and hidden proofs."""
from __future__ import annotations
from dataclasses import asdict, dataclass

PRELUDE = '''import Std
namespace Exp
def size : List Nat → Nat
  | [] => 0
  | _ :: xs => size xs + 1
def total : List Nat → Nat
  | [] => 0
  | x :: xs => x + total xs
def cat : List Nat → List Nat → List Nat
  | [], ys => ys
  | x :: xs, ys => x :: cat xs ys
def bump (n : Nat) : List Nat → List Nat
  | [] => []
  | x :: xs => (n + x) :: bump n xs
def dup : List Nat → List Nat
  | [] => []
  | x :: xs => x :: x :: dup xs
def rev : List Nat → List Nat
  | [] => []
  | x :: xs => cat (rev xs) [x]
def count (n : Nat) : List Nat → Nat
  | [] => 0
  | x :: xs => (if n = x then 1 else 0) + count n xs
def ins (n : Nat) : List Nat → List Nat
  | [] => [n]
  | x :: xs => if n ≤ x then n :: x :: xs else x :: ins n xs
def sort : List Nat → List Nat
  | [] => []
  | x :: xs => ins x (sort xs)
end Exp
open Exp
'''

SIMP = "size, total, cat, bump, dup, count, Nat.add_assoc, Nat.add_comm, Nat.add_left_comm, Nat.mul_add, Nat.add_mul"


def induction_proof(extra=""):
    return "intro xs ys zs n\n  induction xs with\n  | nil => simp [" + SIMP + extra + "]\n  | cons x xs ih => simp_all [" + SIMP + extra + "] <;> omega"


TEMPLATES = [
    ("(xs ++ ys).length = xs.length + ys.length", "intro xs ys zs n\n  simp"),
    ("(xs.map (fun x => x + n)).length = xs.length", "intro xs ys zs n\n  simp"),
    ("xs.reverse.reverse = xs", "intro xs ys zs n\n  simp"),
    ("(xs ++ ys) ++ zs = xs ++ (ys ++ zs)", "intro xs ys zs n\n  simp [List.append_assoc]"),
    ("(xs ++ ys).reverse = ys.reverse ++ xs.reverse", "intro xs ys zs n\n  simp"),
    ("xs ++ [] = xs", "intro xs ys zs n\n  simp"),
    ("(xs ++ ys).map (fun x => n + x) = xs.map (fun x => n + x) ++ ys.map (fun x => n + x)", "intro xs ys zs n\n  simp"),
    ("(xs ++ ys).length = (ys ++ xs).length", "intro xs ys zs n\n  simp [Nat.add_comm]"),
    ("xs.map id = xs", "intro xs ys zs n\n  simp"),
    ("xs.reverse.length = xs.length", "intro xs ys zs n\n  simp"),
    ("count n (cat xs ys) = count n xs + count n ys", induction_proof()),
    ("cat xs [] = xs", induction_proof()),
    ("size (ins n xs) = size xs + 1", "intro xs ys zs n\n  induction xs with\n  | nil => simp [ins, size]\n  | cons x xs ih => simp only [ins]; split <;> simp_all [size, Nat.add_assoc]"),
    ("count n (dup xs) = 2 * count n xs", induction_proof()),
    ("bump 0 xs = xs", induction_proof()),
    ("size xs = xs.length", "intro xs ys zs n\n  induction xs <;> simp_all [size]"),
    ("cat xs ys = xs ++ ys", "intro xs ys zs n\n  induction xs <;> simp_all [cat]"),
    ("dup (bump n xs) = bump n (dup xs)", induction_proof()),
    ("size (sort xs) = size xs", "intro xs ys zs n\n  have hi : ∀ (a : Nat) (ws : List Nat), size (ins a ws) = size ws + 1 := by\n    intro a ws\n    induction ws with\n    | nil => simp [ins, size]\n    | cons x xs ih => simp only [ins]; split <;> simp_all [size, Nat.add_assoc]\n  induction xs with\n  | nil => rfl\n  | cons x xs ih => simp [sort, size, hi, ih]"),
    ("total (ins n xs) = n + total xs", "intro xs ys zs n\n  induction xs with\n  | nil => simp [ins, total]\n  | cons x xs ih => simp only [ins]; split <;> simp_all [total, Nat.add_assoc, Nat.add_comm, Nat.add_left_comm]"),
]


@dataclass
class Task:
    id: str
    family: int
    split: str
    type: str
    dep: str | None
    reference: str

    @property
    def signature(self):
        return f"theorem {self.id} : {self.type}"

    @property
    def stub(self):
        return f"import Deps\nopen Exp\n{self.signature} := by\n  sorry\n"


def root_task(identity, family, split, k):
    prop, proof = TEMPLATES[family]
    # Different splits specialize a common family to disjoint list prefixes.
    # Family, rather than individual variant, is the analysis cluster.
    specialized = prop.replace("xs", f"(List.replicate {k} n ++ xs)")
    ty = f"∀ (xs ys zs : List Nat) (n : Nat), {specialized}"
    generic = f"∀ (xs ys zs : List Nat) (n : Nat), {prop}"
    ref = (f"import Deps\nopen Exp\ntheorem {identity} : {ty} := by\n"
           f"  have h : {generic} := by\n    " + proof.replace("\n", "\n  ") +
           f"\n  intro xs ys zs n\n  exact h (List.replicate {k} n ++ xs) ys zs n\n")
    return Task(identity, family, split, ty, None, ref)


def child_task(identity, parent, split):
    ty = f"({parent.type}) ∧ True"
    ref = f"import Deps\nopen Exp\ntheorem {identity} : {ty} := ⟨{parent.id}, True.intro⟩\n"
    return Task(identity, parent.family, split, ty, parent.id, ref)


def catalogue():
    train, heldout, dev = [], [], []
    for family in range(20):
        previous = root_task(f"L{family:02d}0", family, "train", family % 5 + 1)
        train.append(previous)
        for depth in range(1, 5):
            previous = child_task(f"L{family:02d}{depth}", previous, "train")
            train.append(previous)
        base = root_task(f"H{family:02d}0", family, "heldout", 7)
        heldout.append(base)
        if family < 10:
            heldout.append(child_task(f"H{family:02d}1", base, "heldout"))
        else:
            heldout.append(root_task(f"H{family:02d}1", family, "heldout", 11))
        dev.append(root_task(f"D{family:02d}0", family, "dev", 9))
    return {"train": train, "heldout": heldout, "dev": dev}
