import React, { useEffect, useMemo, useState } from "react";

import {
  Wallet,
  TrendingUp,
  Target,
  Plus,
  Trash2,
  CreditCard,
  Filter,
  AlertTriangle,
  Trophy
} from "lucide-react";

const STORAGE_KEY =
  "financeiro_pessoal_v3";

const categories = [
  "Alimentação",
  "Mercado",
  "Combustível",
  "Pedágio",
  "Saída",
  "Roupa",
  "Saúde",
  "Academia",
  "Lazer",
  "Viagem",
  "Assinaturas",
  "Moradia",
  "Outros"
];

const paymentMethods = [
  "Cartão de Crédito",
  "Pix",
  "Dinheiro",
  "Cartão de Débito"
];

const money = (value) =>
  new Intl.NumberFormat("pt-BR", {
    style: "currency",
    currency: "BRL"
  }).format(Number(value || 0));

const currentMonth =
  new Date().toISOString().slice(0, 7);

export default function App() {
  const [transactions, setTransactions] =
    useState([]);

  const [goals, setGoals] =
    useState([]);

  const [fixedExpenses, setFixedExpenses] =
    useState([]);

  const [cardLimit, setCardLimit] =
    useState(800);

  const [filters, setFilters] =
    useState({
      type: "Todos",
      category: "Todas",
      paymentMethod: "Todos"
    });

  const [form, setForm] = useState({
    date: new Date()
      .toISOString()
      .slice(0, 10),

    type: "Despesa",

    category: "Alimentação",

    paymentMethod:
      "Cartão de Crédito",

    description: "",

    amount: ""
  });

  const [goalForm, setGoalForm] =
    useState({
      name: "",
      target: "",
      current: ""
    });

  const [fixedForm, setFixedForm] =
    useState({
      name: "",
      amount: "",
      dueDay: ""
    });

  useEffect(() => {
    const saved =
      localStorage.getItem(
        STORAGE_KEY
      );

    if (saved) {
      const data = JSON.parse(saved);

      setTransactions(
        data.transactions || []
      );

      setGoals(data.goals || []);

      setFixedExpenses(
        data.fixedExpenses || []
      );

      setCardLimit(
        data.cardLimit || 800
      );
    }
  }, []);

  useEffect(() => {
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        transactions,
        goals,
        fixedExpenses,
        cardLimit
      })
    );
  }, [
    transactions,
    goals,
    fixedExpenses,
    cardLimit
  ]);

  const monthTransactions =
    transactions.filter((item) =>
      item.date?.startsWith(
        currentMonth
      )
    );

  const totals = useMemo(() => {
    const income =
      monthTransactions
        .filter(
          (item) =>
            item.type ===
            "Receita"
        )
        .reduce(
          (sum, item) =>
            sum +
            Number(item.amount),
          0
        );

    const expense =
      monthTransactions
        .filter(
          (item) =>
            item.type ===
            "Despesa"
        )
        .reduce(
          (sum, item) =>
            sum +
            Number(item.amount),
          0
        );

    const creditCard =
      monthTransactions
        .filter(
          (item) =>
            item.paymentMethod ===
              "Cartão de Crédito" &&
            item.type ===
              "Despesa"
        )
        .reduce(
          (sum, item) =>
            sum +
            Number(item.amount),
          0
        );

    const fixed =
      fixedExpenses.reduce(
        (sum, item) =>
          sum +
          Number(item.amount),
        0
      );

    return {
      income,
      expense,
      balance:
        income - expense,
      creditCard,
      fixed,
      realBalance:
        income -
        expense -
        fixed
    };
  }, [
    monthTransactions,
    fixedExpenses
  ]);
  const cardPercent =
    cardLimit > 0
      ? Math.round(
          (totals.creditCard /
            cardLimit) *
            100
        )
      : 0;

  const filteredTransactions =
    transactions.filter((item) => {
      const typeOk =
        filters.type === "Todos" ||
        item.type === filters.type;

      const categoryOk =
        filters.category === "Todas" ||
        item.category ===
          filters.category;

      const paymentOk =
        filters.paymentMethod ===
          "Todos" ||
        item.paymentMethod ===
          filters.paymentMethod;

      return (
        typeOk &&
        categoryOk &&
        paymentOk
      );
    });

  const categoryTotals =
    categories
      .map((cat) => {
        const total =
          monthTransactions
            .filter(
              (item) =>
                item.category ===
                  cat &&
                item.type ===
                  "Despesa"
            )
            .reduce(
              (sum, item) =>
                sum +
                Number(item.amount),
              0
            );

        return {
          category: cat,
          total
        };
      })
      .filter(
        (item) => item.total > 0
      );

  function addTransaction() {
    if (
      !form.description ||
      !form.amount
    )
      return;

    setTransactions([
      {
        id: crypto.randomUUID(),
        ...form,
        amount: Number(
          form.amount
        )
      },
      ...transactions
    ]);

    setForm({
      date: new Date()
        .toISOString()
        .slice(0, 10),
      type: "Despesa",
      category: "Alimentação",
      paymentMethod:
        "Cartão de Crédito",
      description: "",
      amount: ""
    });
  }

  function addGoal() {
    if (
      !goalForm.name ||
      !goalForm.target
    )
      return;

    setGoals([
      {
        id: crypto.randomUUID(),
        name: goalForm.name,
        target: Number(
          goalForm.target
        ),
        current: Number(
          goalForm.current || 0
        ),
        addValue: ""
      },
      ...goals
    ]);

    setGoalForm({
      name: "",
      target: "",
      current: ""
    });
  }

  function addMoneyToGoal(id) {
    setGoals(
      goals.map((goal) => {
        if (goal.id === id) {
          return {
            ...goal,
            current:
              Number(goal.current) +
              Number(
                goal.addValue || 0
              ),
            addValue: ""
          };
        }

        return goal;
      })
    );
  }

  function updateGoalAddValue(
    id,
    value
  ) {
    setGoals(
      goals.map((goal) =>
        goal.id === id
          ? {
              ...goal,
              addValue: value
            }
          : goal
      )
    );
  }

  function addFixedExpense() {
    if (
      !fixedForm.name ||
      !fixedForm.amount
    )
      return;

    setFixedExpenses([
      {
        id: crypto.randomUUID(),
        name: fixedForm.name,
        amount: Number(
          fixedForm.amount
        ),
        dueDay:
          fixedForm.dueDay || "Todo mês"
      },
      ...fixedExpenses
    ]);

    setFixedForm({
      name: "",
      amount: "",
      dueDay: ""
    });
  }
